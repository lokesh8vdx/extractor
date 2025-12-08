"""
Citizens Bank Statement Parser

This module contains the parser function for extracting transactions
from Citizens Bank PDF statements.
"""

import pdfplumber
import re
import pandas as pd


def parse_citizens_bank_statement(pdf_file):
    """
    Extracts structured transaction data from the Citizens Bank PDF statement.
    Also extracts the Account Summary from the first page and Daily Ledger Balances.
    
    Args:
        pdf_file: File-like object (BytesIO or file path) containing the PDF
        
    Returns:
        tuple: (transactions_df, extracted_summary_dict, balance_summary_df)
            - transactions_df: DataFrame with columns: Date, Description, Amount, Type, Source_Page
            - extracted_summary_dict: Dictionary with Account Summary values
            - balance_summary_df: DataFrame with columns: Date, Balance
    """
    transactions = []
    daily_ledger_entries = []
    current_section = "Unknown"
    extracted_summary = {}
    statement_year = None
    
    def parse_amount(amount_str):
        """Cleans and converts amount string to float."""
        if not amount_str:
            return 0.0
        # Remove currency symbols, commas, and whitespace
        clean_str = str(amount_str).replace('$', '').replace(',', '').replace(' ', '').replace('+', '').replace('-', '')
        try:
            return float(clean_str)
        except ValueError:
            return 0.0
    
    # 1. General Pattern for Debits/Deposits: Date (MM/DD) | Amount | Description
    # Note: Amount can start with decimal point (e.g., .31) or have digits before decimal (e.g., 1,234.56)
    date_amount_desc_pattern = re.compile(r'^(\d{2}/\d{2})\s+([\d,]*\.\d{2})\s+(.*)$')
    
    # 2. Check Pattern: Check# (with optional *) | Amount | Date (multi-column format)
    # Handles: "3252 165.00 04/03" or "3255* 891.00 04/03"
    # Also handles lines with two checks: "3252 165.00 04/03 3263 100.00 04/15 TotalChecks"
    # Must exclude "TotalChecks" text at the end
    check_pattern = re.compile(r'(\d+\*?)\s+([\d,]+\.\d{2})\s+(\d{2}/\d{2})(?:\s|$)')
    
    # 3. Daily Balance Pattern: Date (MM/DD) | Balance (multi-column format)
    # Handles: "04/01 1,513.93 04/11 3,021.53 04/22 743.93"
    balance_pattern = re.compile(r'(\d{2}/\d{2})\s+([\d,]+\.\d{2})')

    # Patterns to ignore (Headers, Footers, Page Info)
    ignore_patterns = [
        r'^Page\s+\d+\s+of\s+\d+',
        r'^Clearly Better Business Checking',
        r'^Commercial Account',
        r'^Questions\?',
        r'^CALL:',
        r'^VISIT:',
        r'^MAIL:',
        r'^Accessyouraccountonline',
        r'^citizensbank\.com',
        r'^Beginning\s+',
        r'^through\s+',
        r'^Yournextstatementperiod',
        r'^AsaClearlyBetterBusinessChecking',
        r'^TRANSACTION.*DETAILS',
        r'^PreviousBalance',
        r'^TotalChecks',
        r'^TotalDebits',
        r'^TotalDeposits',
        r'^CurrentBalance',
        r'^BalanceCalculation',
        r'^Date\s+Amount\s+Description',
        r'^Check#\s+Amount\s+Date',
        r'^-\s+[\d,]+\.\d{2}$',  # Lines that are just totals like "- 14,169.02"
        r'^DailyBalance',
        r'^Date\s+Balance',
        r'^PleaseSeeAdditionalInformation',
        r'^\*\*Mayinclude',
        r'^ATM/Purchases',
        r'^OtherDebits',
        r'^Deposits&Credits',
        r'^Deposits&Credit',
        r'^Checks\(Note',
        r'^Debits\*\*',
        r'^Debits\(Continued\)',
        r'^OtherDebits\(Continued\)',
        r'^Deposits&Credits\(Continued\)',
        r'^Continued$',
        r'^SERVICECHARGE',
        r'^WIRETRANSFERFEES',
        r'^STATEMENTDELIVERY',
        r'^NOWNETWORK',
        r'^ZELLE',
        r'^NOWNETID:',
        r'^EPPID:',
        r'^Zelle',
        r'^REALTIMECREDIT',
        r'^PAYPAL',
        r'^SENDERREF:',
        r'^RTPTRACEID:',
        r'^\(MTSNO\.',
        r'^INCOMINGWIRETRANSFER',
    ]
    ignore_regex = re.compile('|'.join(ignore_patterns), re.IGNORECASE)
    
    # Summary Patterns (from first page)
    # Note: Actual format is "PreviousBalance 10,234.83" (no space before number sometimes)
    # "Checks - 14,169.02" (not "TotalChecks")
    # "Debits - 75,884.96" (not "TotalDebits")
    summary_patterns = {
        "Previous Balance": re.compile(r"PreviousBalance\s+([\d,]+\.\d{2})"),
        "Checks": re.compile(r"Checks\s+-\s+([\d,]+\.\d{2})"),
        "Debits": re.compile(r"Debits\s+-\s+([\d,]+\.\d{2})"),
        "Deposits/Credits": re.compile(r"Deposits&Credit\s+\+\s+([\d,]+\.\d{2})"),
        "Current Balance": re.compile(r"CurrentBalance\s+=\s+([\d,]+\.\d{2})")
    }

    # Sections keywords to switch context
    # Note: "Checks(Note..." appears on the same line as the section header
    section_keywords = {
        "Checks(Note": "Checks",  # Match "Checks(Note-checksthatare..."
        "Checks": "Checks",
        "Debits": "Debits",
        "Debits(Continued)": "Debits",
        "OtherDebits": "Debits",
        "OtherDebits(Continued)": "Debits",
        "ATM/Purchases": "Debits",
        "Deposits&Credits": "Deposits",
        "Deposits&Credits(Continued)": "Deposits",
        "Deposits&Credit": "Deposits",
        "DailyBalance": "Daily Balance"
    }

    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            
            # --- Extract Summary from First Page ---
            if idx == 0:
                for key, pattern in summary_patterns.items():
                    match = pattern.search(text)
                    if match:
                        try:
                            val_str = match.group(1).replace(',', '')
                            val = float(val_str)
                            extracted_summary[key] = val
                        except ValueError:
                            extracted_summary[key] = 0.0
                
                # Try to extract year from the first page
                year_match = re.search(r'(20\d{2})', text)
                if year_match:
                    statement_year = year_match.group(1)
                else:
                    # Try to find date range like "04/01/2025 through 04/30/2025"
                    date_range_match = re.search(r'(\d{2}/\d{2})/(\d{4})', text)
                    if date_range_match:
                        statement_year = date_range_match.group(2)
                    else:
                        statement_year = "2025"  # Default year

            lines = text.split('\n')
            
            # Reset last transaction index for the new page 
            last_txn_index = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # --- 1. Detect Section Change ---
                # First check if this line looks like check data - if so, don't treat it as a section header
                looks_like_check_data = bool(check_pattern.search(line))
                
                section_found = False
                if not looks_like_check_data:  # Only check for section headers if it's not check data
                    for key, section_name in section_keywords.items():
                        if key in line:
                            current_section = section_name
                            section_found = True
                            last_txn_index = None # Reset context
                            break
                
                if section_found:
                    continue
                
                # Check for Footer/Noise lines
                if ignore_regex.search(line):
                    last_txn_index = None 
                    continue

                # --- 2. Parse Based on Section Type ---
                
                # LOGIC FOR CHECKS
                if current_section == "Checks":
                    # First, try to extract checks from the line (even if it contains "TotalChecks" at the end)
                    matches = check_pattern.findall(line)
                    
                    # Process any valid checks found
                    valid_checks_found = False
                    if matches:
                        for m in matches:
                            c_num = m[0]
                            c_amt_str = m[1]
                            c_date = m[2]
                            
                            # Skip if check number looks like "TotalChecks" or other non-numeric text
                            # Also skip if the amount or date don't look valid
                            if not c_num.replace('*', '').isdigit():
                                continue
                            if not re.match(r'^[\d,]+\.\d{2}$', c_amt_str):
                                continue
                            if not re.match(r'^\d{2}/\d{2}$', c_date):
                                continue
                            
                            c_desc = f"Check #{c_num.replace('*', '')}"
                            if '*' in c_num:
                                c_desc += " (Out of sequence)"
                            
                            try:
                                amount = parse_amount(c_amt_str)
                                # Checks are always negative (withdrawals)
                                amount = -abs(amount)
                            except ValueError:
                                amount = 0.0
                            
                            # Add year to date
                            full_date = f"{c_date}/{statement_year[-2:]}" if statement_year else f"{c_date}/25"
                            
                            transactions.append({
                                "Date": full_date,
                                "Description": c_desc,
                                "Amount": amount,
                                "Type": "Checks",
                                "Source_Page": page.page_number
                            })
                            valid_checks_found = True
                        
                        if valid_checks_found:
                            last_txn_index = None
                            continue  # Skip further processing if we found valid checks
                    
                    # Only skip lines that are headers, totals, or empty (and didn't contain valid checks)
                    line_upper = line.upper()
                    if (line.strip().startswith('-') or 
                        'TOTALCHECKS' in line_upper or 
                        line.strip() == '' or
                        'Check#' in line or
                        ('Amount' in line and 'Date' in line)):
                        continue 

                # LOGIC FOR DAILY LEDGER
                elif current_section == "Daily Balance":
                    matches = balance_pattern.findall(line)
                    if matches:
                        for m in matches:
                            l_date = m[0]
                            l_bal_str = m[1]
                            try:
                                l_bal = parse_amount(l_bal_str)
                                # Add year to date
                                full_date = f"{l_date}/{statement_year[-2:]}" if statement_year else f"{l_date}/25"
                                daily_ledger_entries.append({
                                    "Date": full_date,
                                    "Balance": l_bal
                                })
                            except ValueError:
                                pass
                    last_txn_index = None

                # LOGIC FOR DEPOSITS AND DEBITS
                elif current_section in ["Deposits", "Debits"]:
                    match = date_amount_desc_pattern.match(line)
                    if match:
                        date = match.group(1)
                        amount_str = match.group(2)
                        description = match.group(3).strip()
                        
                        try:
                            amount = parse_amount(amount_str)
                            # Deposits are positive, Debits are negative
                            if current_section == "Deposits":
                                amount = abs(amount)
                            else:
                                amount = -abs(amount)
                        except ValueError:
                            amount = 0.0

                        # Add year to date
                        full_date = f"{date}/{statement_year[-2:]}" if statement_year else f"{date}/25"

                        transactions.append({
                            "Date": full_date,
                            "Description": description,
                            "Amount": amount,
                            "Type": current_section,
                            "Source_Page": page.page_number
                        })
                        last_txn_index = len(transactions) - 1
                    
                    else:
                        # --- Handle Multi-line Descriptions ---
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not date_amount_desc_pattern.match(clean_line):
                                # Don't append if it looks like a new transaction or header
                                if not any(x in clean_line.upper() for x in ['DATE', 'AMOUNT', 'DESCRIPTION', 'TOTAL', 'CONTINUED']):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
    
    return pd.DataFrame(transactions), extracted_summary, pd.DataFrame(daily_ledger_entries)
