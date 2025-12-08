"""
US Bank Statement Parser

This module contains the parser function for extracting transactions
from U.S. Bank PDF statements.
"""

import pdfplumber
import re
import pandas as pd


def parse_us_bank_statement(pdf_file):
    """
    Extracts structured transaction data from the U.S. Bank PDF statement.
    Also extracts the Account Summary and Balance Summary.
    
    Args:
        pdf_file: File-like object (BytesIO or file path) containing the PDF
        
    Returns:
        tuple: (transactions_df, extracted_summary_dict, balance_summary_df)
            - transactions_df: DataFrame with columns: Date, Description, Ref Number, Amount, Type, Source_Page, Extraction_Seq
            - extracted_summary_dict: Dictionary with Account Summary values
            - balance_summary_df: DataFrame with columns: Date, Balance
    """
    transactions = []
    balance_summary_entries = []
    current_section = "Unknown"
    extracted_summary = {}
    extraction_seq = 0  # Counter for extraction sequence
    
    # Month abbreviations to numbers mapping
    month_map = {
        'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
        'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
        'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
    }
    
    # 0. Pattern for Customer Deposits: Date Ref Number Amount
    customer_deposit_pattern = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+([A-Z0-9_\-]+)\s+([\d,]+\.\d{2})')
    
    # 1. Pattern for Other Deposits: Date Description [Ref Number] [Amount with optional $]
    deposit_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})$')
    
    # Pattern for Card Deposits: Date Description [Ref Number] Amount
    card_deposit_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})$')
    
    # 2. Pattern for Card Withdrawals: Date Description Ref Number Amount
    card_withdrawal_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})-?$')
    
    # 3. Pattern for Other Withdrawals: Date Description [Ref Number] Amount
    other_withdrawal_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})-?$')
    
    # 4. Pattern for Checks: Check Number Date Ref Number Amount
    check_pattern = re.compile(r'\b(\d{3,}\*?|\d{2}\*)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+([A-Z0-9_\-]+)\s+([\d,]+\.\d{2})')
    
    # 5. Pattern for Balance Summary: Date Ending Balance
    balance_pattern = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+((?:-)?[\d,]+\.\d{2}-?)')
    
    # Patterns to ignore (Headers, Footers, Page Info)
    ignore_patterns = [
        r'^Date\s+Description',
        r'^Page\s+\d+\s+of\s+\d+',
        r'^continued\s+on\s+the\s+next\s+page',
        r'^Account\s+Number',
        r'^U\.S\.\s+BANK',
        r'^Business\s+Statement',
        r'^Member\s+FDIC',
        r'^Total\s+',
        r'^Card\s+Number',
        r'^Card\s+.*?Subtotal',
        r'^Subtotal',
        r'^Balance\s+Summary',
        r'^Date\s+Ending\s+Balance',
        r'^Balances\s+only\s+appear',
        r'^ANALYSIS\s+SERVICE',
        r'^Account\s+Analysis',
        r'^Service\s+Activity',
        r'^Fee\s+Based',
        r'^Ref\s+Number',
        r'^Check\s+Date\s+Ref\s+Number',
        r'^Conventional\s+Checks',
        r'^Checks\s+Presented',
        r'^\*\s+Gap\s+in\s+check',
        r'^Number\s+Date\s+Ref\s+Number\s+Amount',
    ]
    ignore_regex = re.compile('|'.join(ignore_patterns), re.IGNORECASE)
    
    # Summary Patterns for Account Summary section
    summary_patterns = {
        "Beginning Balance": [
            re.compile(r"Beginning Balance on .*?\$\s+((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"Beginning Balance.*?((?:-)?[\d,]+\.\d{2})")
        ],
        "Customer Deposits": [
            re.compile(r"Total Customer Deposits\s+\$\s*((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"^Customer Deposits\s+\d+\s+((?:-)?[\d,]+\.\d{2})$"),
            re.compile(r"^Customer Deposits\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})$"),
        ],
        "Other Deposits": [
            re.compile(r"Total Other Deposits\s+\$\s*((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"^Other Deposits\s+\d+\s+((?:-)?[\d,]+\.\d{2})$"),
            re.compile(r"^Other Deposits\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})$"),
        ],
        "Card Deposits": [
            re.compile(r"Total Card Deposits\s+\$\s*((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"^Card Deposits\s+\d+\s+((?:-)?[\d,]+\.\d{2})$"),
            re.compile(r"^Card Deposits\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})$"),
        ],
        "Card Withdrawals": [
            re.compile(r"Card Withdrawals\s+\d+\s+((?:-)?[\d,]+\.\d{2})-?"),
            re.compile(r"Card Withdrawals\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})-?"),
            re.compile(r"Card Withdrawals.*?((?:-)?[\d,]+\.\d{2})-?")
        ],
        "Other Withdrawals": [
            re.compile(r"Other Withdrawals\s+\d+\s+((?:-)?[\d,]+\.\d{2})-?"),
            re.compile(r"Other Withdrawals\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})-?"),
            re.compile(r"Other Withdrawals.*?((?:-)?[\d,]+\.\d{2})-?")
        ],
        "Checks Paid": [
            re.compile(r"Checks Paid\s+\d+\s+((?:-)?[\d,]+\.\d{2})-?"),
            re.compile(r"Checks Paid\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})-?"),
            re.compile(r"Checks Paid.*?((?:-)?[\d,]+\.\d{2})-?")
        ],
        "Ending Balance": [
            re.compile(r"Ending Balance on .*?\$\s+((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"Ending Balance.*?((?:-)?[\d,]+\.\d{2})")
        ]
    }
    
    # Sections keywords to switch context
    section_keywords = {
        "Customer Deposits": "Customer Deposits",
        "Other Deposits": "Other Deposits",
        "Card Deposits": "Card Deposits",
        "Card Withdrawals": "Card Withdrawals",
        "Other Withdrawals": "Other Withdrawals",
        "Checks Paid": "Checks Paid",
        "Checks Presented": "Checks Paid",
        "Checks Presented Conventionally": "Checks Paid",
        "Balance Summary": "Balance Summary"
    }
    
    # Extract year from statement period
    statement_year = None
    
    # Reset file pointer
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)
    
    with pdfplumber.open(pdf_file) as pdf:
        total_pages = len(pdf.pages)
        
        for idx, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            
            # Extract year from statement period on first transaction page
            if statement_year is None:
                year_match = re.search(r'Statement Period:\s*(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+(\d{4})', text)
                if year_match:
                    statement_year = year_match.group(2)
            
            # Extract Summary from Account Summary section
            if "Account Summary" in text:
                lines = text.split('\n')
                in_summary = False
                summary_end_markers = ["Date Description", "Card Number", "Check Number", "Analysis", "Service Activity"]
                
                for line in lines:
                    # Detect Account Summary section boundaries
                    if "Account Summary" in line:
                        in_summary = True
                    elif in_summary and any(marker in line for marker in summary_end_markers):
                        break
                    
                    # Only extract from summary header lines (not transaction details)
                    if in_summary:
                        for key, patterns in summary_patterns.items():
                            # Skip if already extracted (prefer first match, usually more specific)
                            if key in extracted_summary:
                                continue
                            # Try each pattern in order until one matches
                            for pattern in patterns:
                                match = pattern.search(line)
                                if match:
                                    try:
                                        val_str = match.group(1).replace(',', '').replace('-', '-')
                                        val = float(val_str)
                                        extracted_summary[key] = val
                                        break  # Found a match, move to next category
                                    except (ValueError, IndexError):
                                        pass  # Try next pattern
            
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
                        last_txn_index = None  # Reset context
                        break
                
                if section_found:
                    continue
                
                # Check for Footer/Noise lines
                if ignore_regex.search(line):
                    last_txn_index = None
                    continue
                
                # Skip empty lines
                if not line.strip():
                    continue
                
                # --- 2. Parse Based on Section Type ---
                
                # LOGIC FOR CUSTOMER DEPOSITS
                if current_section == "Customer Deposits":
                    matches = customer_deposit_pattern.findall(line.strip())
                    if matches:
                        for match in matches:
                            month_abbr = match[0]
                            day = match[1].zfill(2)
                            ref_number = match[2]
                            amount_str = match[3].replace(',', '')
                            
                            month_num = month_map.get(month_abbr, '01')
                            if statement_year:
                                date = f"{month_num}/{day}/{statement_year[-2:]}"
                            else:
                                date = f"{month_num}/{day}/25"
                            
                            try:
                                amount = float(amount_str)
                            except ValueError:
                                amount = 0.0
                            
                            extraction_seq += 1
                            transactions.append({
                                "Date": date,
                                "Description": "Customer Deposit",
                                "Ref Number": ref_number,
                                "Amount": amount,
                                "Type": "Customer Deposits",
                                "Source_Page": page.page_number,
                                "Extraction_Seq": extraction_seq
                            })
                
                # LOGIC FOR OTHER DEPOSITS
                elif current_section == "Other Deposits":
                    match = deposit_pattern.match(line.strip())
                    if match:
                        month_abbr = match.group(1)
                        day = match.group(2).zfill(2)
                        description_and_ref = match.group(3).strip()
                        amount_str = match.group(4).replace(',', '')
                        
                        ref_match = re.search(r'\s+([A-Z0-9_\-]{8,})$', description_and_ref)
                        if ref_match:
                            ref_number = ref_match.group(1)
                            description = description_and_ref[:description_and_ref.rfind(ref_number)].strip()
                        else:
                            parts = description_and_ref.split()
                            if len(parts) > 1 and re.match(r'^[A-Z0-9_\-]{6,}$', parts[-1]):
                                ref_number = parts[-1]
                                description = ' '.join(parts[:-1])
                            else:
                                ref_number = ""
                                description = description_and_ref
                        
                        month_num = month_map.get(month_abbr, '01')
                        if statement_year:
                            date = f"{month_num}/{day}/{statement_year[-2:]}"
                        else:
                            date = f"{month_num}/{day}/25"
                        
                        try:
                            amount = float(amount_str)
                        except ValueError:
                            amount = 0.0
                        
                        extraction_seq += 1
                        transactions.append({
                            "Date": date,
                            "Description": description,
                            "Ref Number": ref_number,
                            "Amount": amount,
                            "Type": "Other Deposits",
                            "Source_Page": page.page_number,
                            "Extraction_Seq": extraction_seq
                        })
                        last_txn_index = len(transactions) - 1
                    else:
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not clean_line.startswith('$') and not re.match(r'^Total\s+', clean_line, re.IGNORECASE):
                                if clean_line.startswith('On ') or clean_line.startswith('REF='):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                                elif not re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', clean_line):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                
                # LOGIC FOR CARD DEPOSITS
                elif current_section == "Card Deposits":
                    match = card_deposit_pattern.match(line.strip())
                    if match:
                        month_abbr = match.group(1)
                        day = match.group(2).zfill(2)
                        description_and_ref = match.group(3).strip()
                        amount_str = match.group(4).replace(',', '')
                        
                        ref_number = ""
                        description = description_and_ref
                        
                        month_num = month_map.get(month_abbr, '01')
                        if statement_year:
                            date = f"{month_num}/{day}/{statement_year[-2:]}"
                        else:
                            date = f"{month_num}/{day}/25"
                        
                        try:
                            amount = float(amount_str)
                        except ValueError:
                            amount = 0.0
                        
                        extraction_seq += 1
                        transactions.append({
                            "Date": date,
                            "Description": description,
                            "Ref Number": ref_number,
                            "Amount": amount,
                            "Type": "Card Deposits",
                            "Source_Page": page.page_number,
                            "Extraction_Seq": extraction_seq
                        })
                        last_txn_index = len(transactions) - 1
                    else:
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not clean_line.startswith('$') and not re.match(r'^Total\s+', clean_line, re.IGNORECASE):
                                if clean_line.startswith('Serial No.'):
                                    current_ref = transactions[last_txn_index]["Ref Number"]
                                    if not current_ref:
                                        transactions[last_txn_index]["Ref Number"] = clean_line.replace('Serial No.', '').strip()
                                    else:
                                        transactions[last_txn_index]["Description"] += " " + clean_line
                                elif not re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', clean_line):
                                    transactions[last_txn_index]["Description"] += " " + clean_line

                # LOGIC FOR CARD WITHDRAWALS
                elif current_section == "Card Withdrawals":
                    match = card_withdrawal_pattern.match(line.strip())
                    if match:
                        month_abbr = match.group(1)
                        day = match.group(2).zfill(2)
                        description_and_ref = match.group(3).strip()
                        amount_str = match.group(4).replace(',', '')
                        
                        ref_match = re.search(r'\s+([A-Z0-9_\-]{8,})$', description_and_ref)
                        if ref_match:
                            ref_number = ref_match.group(1)
                            description = description_and_ref[:description_and_ref.rfind(ref_number)].strip()
                        else:
                            parts = description_and_ref.split()
                            if len(parts) > 1 and re.match(r'^[A-Z0-9_\-]{6,}$', parts[-1]):
                                ref_number = parts[-1]
                                description = ' '.join(parts[:-1])
                            else:
                                ref_number = ""
                                description = description_and_ref
                        
                        month_num = month_map.get(month_abbr, '01')
                        if statement_year:
                            date = f"{month_num}/{day}/{statement_year[-2:]}"
                        else:
                            date = f"{month_num}/{day}/25"
                        
                        try:
                            amount = -float(amount_str)  # Negative for withdrawals
                        except ValueError:
                            amount = 0.0
                        
                        extraction_seq += 1
                        transactions.append({
                            "Date": date,
                            "Description": description,
                            "Ref Number": ref_number,
                            "Amount": amount,
                            "Type": "Card Withdrawals",
                            "Source_Page": page.page_number,
                            "Extraction_Seq": extraction_seq
                        })
                        last_txn_index = len(transactions) - 1
                    else:
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not clean_line.startswith('$') and not clean_line.startswith('************'):
                                if clean_line.startswith('REF #') or clean_line.startswith('REF='):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                                elif not re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', clean_line):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                
                # LOGIC FOR OTHER WITHDRAWALS
                elif current_section == "Other Withdrawals":
                    match = other_withdrawal_pattern.match(line.strip())
                    if match:
                        month_abbr = match.group(1)
                        day = match.group(2).zfill(2)
                        description_and_ref = match.group(3).strip()
                        amount_str = match.group(4).replace(',', '')
                        
                        ref_match = re.search(r'\s+([A-Z0-9_\-]{8,})$', description_and_ref)
                        if ref_match:
                            ref_number = ref_match.group(1)
                            description = description_and_ref[:description_and_ref.rfind(ref_number)].strip()
                        else:
                            parts = description_and_ref.split()
                            if len(parts) > 1 and re.match(r'^[A-Z0-9_\-]{6,}$', parts[-1]):
                                ref_number = parts[-1]
                                description = ' '.join(parts[:-1])
                            else:
                                ref_number = ""
                                description = description_and_ref
                        
                        month_num = month_map.get(month_abbr, '01')
                        if statement_year:
                            date = f"{month_num}/{day}/{statement_year[-2:]}"
                        else:
                            date = f"{month_num}/{day}/25"
                        
                        try:
                            amount = -float(amount_str)  # Negative for withdrawals
                        except ValueError:
                            amount = 0.0
                        
                        extraction_seq += 1
                        transactions.append({
                            "Date": date,
                            "Description": description,
                            "Ref Number": ref_number,
                            "Amount": amount,
                            "Type": "Other Withdrawals",
                            "Source_Page": page.page_number,
                            "Extraction_Seq": extraction_seq
                        })
                        last_txn_index = len(transactions) - 1
                    else:
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not clean_line.startswith('$') and not re.match(r'^Total\s+', clean_line, re.IGNORECASE):
                                if clean_line.startswith('REF='):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                                elif not re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', clean_line):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                
                # LOGIC FOR CHECKS PAID
                elif current_section == "Checks Paid":
                    matches = check_pattern.findall(line.strip())
                    if matches:
                        for match in matches:
                            check_num = match[0]
                            month_abbr = match[1]
                            day = match[2].zfill(2)
                            ref_number = match[3]
                            amount_str = match[4].replace(',', '')
                            
                            month_num = month_map.get(month_abbr, '01')
                            if statement_year:
                                date = f"{month_num}/{day}/{statement_year[-2:]}"
                            else:
                                date = f"{month_num}/{day}/25"
                            
                            try:
                                amount = -float(amount_str)  # Negative for checks
                            except ValueError:
                                amount = 0.0
                            
                            extraction_seq += 1
                            transactions.append({
                                "Date": date,
                                "Description": f"Check #{check_num}",
                                "Ref Number": ref_number,
                                "Amount": amount,
                                "Type": "Checks Paid",
                                "Source_Page": page.page_number,
                                "Extraction_Seq": extraction_seq
                            })
                
                # LOGIC FOR BALANCE SUMMARY
                elif current_section == "Balance Summary":
                    stripped_line = line.strip()
                    if check_pattern.search(stripped_line) or re.match(r'^\d{3,}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}', stripped_line):
                        continue
                    
                    matches = balance_pattern.findall(line)
                    if matches:
                        for match in matches:
                            month_abbr = match[0]
                            day = match[1].zfill(2)
                            balance_str = match[2].replace(',', '')
                            
                            if balance_str.endswith('-'):
                                balance_str = '-' + balance_str[:-1]
                                
                            month_num = month_map.get(month_abbr, '01')
                            if statement_year:
                                date = f"{month_num}/{day}/{statement_year[-2:]}"
                            else:
                                date = f"{month_num}/{day}/25"
                            
                            try:
                                balance = float(balance_str)
                                balance_summary_entries.append({
                                    "Date": date,
                                    "Balance": balance
                                })
                            except ValueError:
                                pass
    
    return pd.DataFrame(transactions), extracted_summary, pd.DataFrame(balance_summary_entries)
