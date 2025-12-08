"""
Bank of America Statement Parser

This module contains the parser function for extracting transactions
from Bank of America PDF statements.
"""

import pdfplumber
import re
import pandas as pd


def parse_boa_statement(pdf_file):
    """
    Extracts structured transaction data from the Bank of America PDF statement.
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
    raw_ledger_entries = [] # Store raw MM/DD dates first
    current_section = "Unknown"
    extracted_summary = {}
    statement_year = None
    
    # 1. General Pattern: Date at start, Description in middle, Amount at end
    date_start_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.*?)(\-?[\d,]+\.\d{2})$')
    
    # 2. Specific Check Pattern: Date | Optional Check # | Amount
    check_pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+(?:(\d+\*?)\s+)?(\-?[\d,]+\.\d{2})')
    
    # 3. Daily Ledger Pattern: Date (MM/DD) | Balance
    # Handles multiple entries per line: 04/01 923.52 04/11 426.89
    ledger_pattern = re.compile(r'(\d{2}/\d{2})\s+((?:-)?[\d,]+\.\d{2})')

    # Patterns to ignore (Headers, Footers, Page Info)
    ignore_patterns = [
        r'^Date\s+Description\s+Amount',
        r'^Page\s+\d+\s+of\s+\d+',
        r'^continued\s+on\s+the\s+next\s+page',
        r'^Account\s+#',
        r'^Bank\s+of\s+America',
        r'^Your\s+checking\s+account',
        r'^Total\s+', 
        r'^©\d{4}',
        r'^Mobile\s+Banking',
        r'^Message\s+and\s+data',
        r'^Fees\s+or\s+other',
        r'^See\s+the\s+big\s+picture',
        r'^Scan\s+the\s+code',
        r'^Use\s+our\s+app',
        r'^When\s+you\s+use',
        r'^Available\s+in\s+',
        r'^Send\s+wire\s+transfers',
        r'^Data\s+connection\s+required',
        r'^To\s+learn\s+more',
        r'^Subtotal\s+',
        r'^Note\s+your\s+Ending\s+Balance',
        r'^Date\s+Balance\s+\(\$\)' # Header for ledger
    ]
    ignore_regex = re.compile('|'.join(ignore_patterns), re.IGNORECASE)
    
    # Summary Patterns
    summary_patterns = {
        "Beginning Balance": re.compile(r"Beginning balance on .*? ((?:-)?\$?[\d,]+\.\d{2})"),
        "Deposits/Credits": re.compile(r"Deposits and other credits\s+((?:-)?\$?[\d,]+\.\d{2})"),
        "Withdrawals/Debits": re.compile(r"Withdrawals and other debits\s+((?:-)?\$?[\d,]+\.\d{2})"),
        "Checks": re.compile(r"Checks\s+((?:-)?\$?[\d,]+\.\d{2})"),
        "Service Fees": re.compile(r"Service fees\s+((?:-)?\$?[\d,]+\.\d{2})"),
        "Ending Balance": re.compile(r"Ending balance on .*? ((?:-)?\$?[\d,]+\.\d{2})")
    }

    # Sections keywords to switch context
    section_keywords = {
        "Deposits and other credits": "Deposits",
        "Withdrawals and other debits": "Withdrawals",
        "Checks": "Checks",
        "Service fees": "Service Fees",
        "Daily ledger balances": "Daily Ledger"
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
                            val_str = match.group(1).replace('$', '').replace(',', '')
                            val = float(val_str)
                            extracted_summary[key] = val
                        except ValueError:
                            extracted_summary[key] = 0.0
                
                # Initial year guess from text
                year_match = re.search(r'(20\d{2})', text)
                if year_match:
                    statement_year = year_match.group(1)

            lines = text.split('\n')
            
            # Reset last transaction index for the new page 
            last_txn_index = None
            
            for line in lines:
                # --- 1. Detect Section Change ---
                section_found = False
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
                    matches = check_pattern.findall(line)
                    
                    if matches:
                        for m in matches:
                            c_date = m[0]
                            c_num = m[1]
                            c_amt_str = m[2].replace(',', '')
                            
                            if c_num:
                                c_desc = f"Check #{c_num}"
                            else:
                                c_desc = "Check (No #)"
                            
                            try:
                                amount = float(c_amt_str)
                            except ValueError:
                                amount = 0.0
                            
                            transactions.append({
                                "Date": c_date,
                                "Description": c_desc,
                                "Amount": amount,
                                "Type": current_section,
                                "Source_Page": page.page_number
                            })
                        last_txn_index = None 

                # LOGIC FOR DAILY LEDGER
                elif current_section == "Daily Ledger":
                    matches = ledger_pattern.findall(line)
                    if matches:
                        for m in matches:
                            l_date = m[0]
                            l_bal_str = m[1].replace(',', '')
                            try:
                                l_bal = float(l_bal_str)
                                # Store raw date for now
                                raw_ledger_entries.append({
                                    "RawDate": l_date,
                                    "Balance": l_bal
                                })
                            except ValueError:
                                pass
                    last_txn_index = None

                # LOGIC FOR DEPOSITS, WITHDRAWALS, FEES
                elif current_section in ["Deposits", "Withdrawals", "Service Fees"]:
                    match = date_start_pattern.match(line)
                    if match:
                        date = match.group(1)
                        description = match.group(2).strip()
                        amount_str = match.group(3).replace(',', '')
                        
                        try:
                            amount = float(amount_str)
                        except ValueError:
                            amount = 0.0

                        transactions.append({
                            "Date": date,
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
                            if clean_line:
                                transactions[last_txn_index]["Description"] += " " + clean_line
    
    # Post-process to determine correct year for ledger entries
    year_2digit = "25" # Default
    
    if transactions:
        # Get year from first transaction
        first_date = transactions[0]['Date'] # MM/DD/YY
        try:
            parts = first_date.split('/')
            if len(parts) == 3:
                year_2digit = parts[2]
        except:
            pass
    elif statement_year:
        year_2digit = statement_year[-2:]
        
    # Create final ledger dataframe with corrected year
    daily_ledger_entries = []
    for entry in raw_ledger_entries:
        daily_ledger_entries.append({
            "Date": f"{entry['RawDate']}/{year_2digit}",
            "Balance": entry['Balance']
        })
        
    return pd.DataFrame(transactions), extracted_summary, pd.DataFrame(daily_ledger_entries)
