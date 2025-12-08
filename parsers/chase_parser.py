"""
Chase Bank Statement Parser

This module contains the parser function for extracting transactions
from Chase Bank PDF statements.
"""

import pdfplumber
import re
import pandas as pd

def parse_amount(amount_str):
    """Cleans and converts amount string to float."""
    if not amount_str:
        return 0.0
    # Remove currency symbols and commas
    clean_str = amount_str.replace('$', '').replace(',', '').replace(' ', '')
    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def parse_chase_statement(pdf_file):
    """
    Extracts structured transaction data from the Chase Bank PDF statement.
    Also extracts the Account Summary and Daily Balance Summary.
    
    Args:
        pdf_file: File-like object (BytesIO or file path) containing the PDF
        
    Returns:
        tuple: (transactions_df, extracted_summary_dict, balance_summary_df)
            - transactions_df: DataFrame with columns: Date, Description, Amount, Type, Page
            - extracted_summary_dict: Dictionary with Account Summary values
            - balance_summary_df: DataFrame with columns: Date, Balance, Page
    """
    transactions = []
    balances = []
    checking_summary = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            # Extract text with layout preservation
            # Reduced y_tolerance to handle interleaved hidden text (e.g. "checks paid section" overlapping with check numbers)
            text = page.extract_text(x_tolerance=2, y_tolerance=0.3)
            if not text:
                continue
            lines = text.split('\n')
            
            # Chase Statement Logic
            # We look for lines that start with a date pattern like MM/DD
            # Modified Regex to handle lines with prefix noise (e.g. *end* markers)
            # Matches: Optional prefix, Date (MM/DD or /DD), Description, Amount at end
            # Relaxed end-of-line constraint to handle page number/footer noise at end of line
            date_pattern = re.compile(r'(?:.*?)\s*(\d{0,2}/\d{2})\s+(.*)\s+(-?\$?[\d,]+\.\d{2})(?:\s.*)?$')
            
            # Pattern for Checks Paid: Check No, Description (optional), Date, Amount
            # Updated to match date_pattern flexibility (prefix noise, partial dates)
            # Relaxed end-of-line constraint here as well
            check_pattern = re.compile(r'(?:.*?)\s*(\d+)\s+(.*?)\s+(\d{0,2}/\d{2})\s+(-?\$?[\d,]+\.\d{2})(?:\s.*)?$')
            
            # Pattern for Balance History (multi-column)
            # Finds all occurrences of "Date Amount" pairs in a line
            # Updated to allow optional space before slash (e.g. "03 /11")
            balance_pattern = re.compile(r'(\d{0,2}\s?/\d{2})\s+(-?\$?[\d,]+\.\d{2})')

            # Pattern for Checking Summary
            # Matches: Label (text), Optional Count (int), Amount (currency)
            summary_pattern = re.compile(r'^(.*?)\s+(?:(\d+)\s+)?(-?\$?[\d,]+\.\d{2})$')

            current_section = None
            
            for line in lines:
                line = line.strip()
                
                # Global Noise Filtering
                # Skip watermark lines
                if "WM" in line and "bbcd" in line:
                    continue
                if line.startswith("WM") or "%%WM" in line:
                    continue
                
                # Skip hidden text markers if they appear on their own line
                # Also skip "Total Checks Paid" footer and common disclaimer text
                if "*start*" in line or "*end*" in line or "Total Checks Paid" in line:
                    continue
                
                if "If you see a description" in line or "return the check to you" in line:
                    continue
                
                if "All of your recent checks" in line or "An image of this check" in line:
                    continue
                
                # Additional specific filter for broken disclaimer line
                if "one of your previous statements" in line:
                    continue
                
                # Filter out single letter noise lines like "d d", "c c"
                if re.match(r'^([a-zA-Z]\s)+[a-zA-Z]$', line) and len(line) < 10:
                    continue

                # Skip "Total ..." footer lines for various sections
                if line.startswith("Total ") and ("Deposits" in line or "Withdrawals" in line or "Fees" in line or "Purchases" in line or "Credits" in line):
                    continue
                
                if "ATM & Debit Card Totals" in line:
                    continue

                # Detect Sections to categorize transactions
                if "CHECKING SUMMARY" in line:
                    current_section = "Checking Summary"
                    continue
                elif "DEPOSITS AND ADDITIONS" in line:
                    current_section = "Deposit"
                    continue
                elif "CHECKS PAID" in line:
                    current_section = "Checks Paid"
                    continue
                elif "ATM & DEBIT CARD WITHDRAWALS" in line:
                    current_section = "ATM & Debit Withdrawal"
                    continue
                elif "ELECTRONIC WITHDRAWALS" in line:
                    current_section = "Electronic Withdrawal"
                    continue
                elif "OTHER WITHDRAWALS" in line:
                    current_section = "Other Withdrawal"
                    continue
                elif "FEES" in line:
                    current_section = "Fee"
                    continue
                # Stop processing when reaching Daily Ending Balance to avoid mixing it with Fees
                elif "DAILY ENDING BALANCE" in line:
                    current_section = "Daily Ending Balance"
                    continue
                
                # Skip irrelevant header/footer lines
                if "Page" in line or "Account Number" in line or "Opening Balance" in line:
                    # Exception: Opening Balance might be part of Checking Summary
                    if current_section != "Checking Summary":
                        continue

                # HANDLE CHECKING SUMMARY SECTION
                if current_section == "Checking Summary":
                    # Stop if we hit another section (though usually it's at the top)
                    # or if line is just a date range or empty
                    if "Account Number" in line: 
                        continue
                        
                    match = summary_pattern.match(line)
                    if match:
                        label, count, amount_str = match.groups()
                        
                        # Filter out likely false positives if any
                        if "Page" in label: 
                            continue

                        amount = parse_amount(amount_str)
                        checking_summary.append({
                            "Description": label.strip(),
                            "Count": int(count) if count else None,
                            "Amount": amount
                        })
                    # If we hit a line that doesn't match summary pattern but looks like next section header, break section
                    elif "DEPOSITS" in line or "CHECKS" in line:
                        # Transition handled by main loop next iter usually
                        pass
                    continue

                # HANDLE DAILY ENDING BALANCE SECTION
                if current_section == "Daily Ending Balance":
                    # Find all date-amount pairs in the line
                    matches = balance_pattern.findall(line)
                    if matches:
                        for date, amount_str in matches:
                            # Remove potential spaces captured by regex
                            date = date.replace(' ', '')
                            
                            # Fix date year if needed
                            if date.startswith('/'):
                                if balances:
                                    last_date = balances[-1]['Date']
                                    # Handle potential full date format MM/DD/YY in last_date
                                    parts = last_date.split('/')
                                    last_month = parts[0]
                                    last_day = parts[1]
                                    
                                    current_day_str = date.replace('/', '')
                                    
                                    try:
                                        cur_d = int(current_day_str)
                                        lst_d = int(last_day)
                                        lst_m = int(last_month)
                                        
                                        # Heuristic: If current day is significantly smaller than last day, 
                                        # it's likely the next month (e.g. 28 -> 02)
                                        if cur_d < lst_d:
                                            new_month = lst_m + 1
                                            if new_month > 12: new_month = 1
                                            date = f"{new_month:02d}{date}"
                                        else:
                                            date = f"{last_month}{date}"
                                    except ValueError:
                                        date = f"{last_month}{date}"
                                else:
                                    date = f"04{date}" # Fallback
                            else:
                                # Sequential Validation Logic
                                # Since Daily Ending Balances must be chronological,
                                # we check if the current date seems to "jump back" in time (e.g. 03/10 -> 02/11).
                                # This handles noise like "balance2/11" being parsed as "2/11" instead of "03/11".
                                if balances:
                                    try:
                                        last_date = balances[-1]['Date']
                                        last_m_str, last_d_str = last_date.split('/')
                                        last_m = int(last_m_str)
                                        
                                        # Clean current date parts
                                        cur_parts = date.split('/')
                                        if len(cur_parts) == 2:
                                            cur_m = int(cur_parts[0])
                                            
                                            # Check for backward month jump (excluding Dec -> Jan)
                                            # If cur_m < last_m and not (last_m == 12 and cur_m == 1):
                                                # It's likely a corrupted month digit.
                                                # We assume it belongs to the same month (or next, but rarely skips back)
                                                # Since 11 > 10 (in 03/10 -> 2/11 example), using last_m (03) makes it 03/11 which is valid.
                                                
                                                # But what if it SHOULD be next month? e.g. 03/31 -> 2/01 (noise for 04/01)?
                                                # If we force 03/01, it's still < 03/31.
                                                # So we might need to check days too.
                                                
                                                # Simple robust fix for "balance2/11" case:
                                                # If cur_m is clearly wrong (backwards), try last_m.
                                                # If changing to last_m makes it chronological (or close), use it.
                                                
                                                # Update date to use last_m
                                            date = f"{last_m:02d}/{cur_parts[1]}"
                                    except (ValueError, IndexError):
                                        pass
                                
                            amount = parse_amount(amount_str)
                            balances.append({
                                "Date": date,
                                "Amount": amount,
                                "Page": page_num
                            })
                        continue

                # HANDLE CHECKS PAID SECTION
                if current_section == "Checks Paid":
                    match = check_pattern.search(line)
                    if match:
                        check_num, desc_text, date, amount_str = match.groups()
                        
                        # Date fix logic for checks (usually standard MM/DD but consistent with others)
                        if date.startswith('/'):
                            if transactions:
                                last_month = transactions[-1]['Date'].split('/')[0]
                                date = f"{last_month}{date}"
                            else:
                                date = f"04{date}" # Default fallback

                        desc = f"Check #{check_num} {desc_text.strip()}"
                        amount = parse_amount(amount_str)
                        
                        # Keep amount positive (like working chase.py)
                        amount = abs(amount)
                        
                        transactions.append({
                            "Date": date,
                            "Description": desc,
                            "Amount": amount,
                            "Type": current_section,
                            "Page": page_num
                        })
                        continue

                # Try to match a transaction line using search (allows prefix match)
                match = None
                if current_section not in ["Checks Paid", "Daily Ending Balance", "Checking Summary"]:
                    match = date_pattern.match(line)
                    if not match:
                        # Retry with search for cases where date isn't at start
                        match = date_pattern.search(line)
                
                if match and current_section:
                    date, desc, amount_str = match.groups()
                    
                    # Fix corrupted dates (e.g. "/14" -> "04/14") found in noisy lines
                    if date.startswith('/'):
                        # Use previous transaction month or default to 04 (April) if unknown
                        if transactions:
                            last_month = transactions[-1]['Date'].split('/')[0]
                            date = f"{last_month}{date}"
                        else:
                            date = f"04{date}" 
                    
                    # Clean up description (remove extra spaces)
                    desc = desc.strip()
                    
                    # Parse amount
                    amount = parse_amount(amount_str)
                    
                    # Keep all amounts positive (like working chase.py)
                    # main_app.py determines direction based on Type field
                    amount = abs(amount)
                    
                    transactions.append({
                        "Date": date,
                        "Description": desc,
                        "Amount": amount,
                        "Type": current_section,
                        "Page": page_num 
                    })
                
                # HANDLE MULTI-LINE DESCRIPTIONS
                # If a line doesn't start with a date but we just added a transaction,
                # it's likely a continuation of the previous description.
                elif transactions and not re.match(r'\d{2}/\d{2}', line) and \
                     not (current_section == "Checks Paid" and re.match(r'^\d+', line)) and \
                     current_section not in ["Daily Ending Balance", "Checking Summary"]:
                    
                    # Ensure we don't append lines from a new page to a previous page's transaction
                    if transactions[-1]['Page'] != page_num:
                        continue
                    
                    # Ensure we don't append lines if the section has changed
                    if current_section != transactions[-1]['Type']:
                        continue

                    # Skip if it looks like a balance summary line (Chase specific noise)
                    if "$" in line and "Balance" in line:
                        continue

                    # Clean debug markers from the line
                    if "*start*" in line or "*end*" in line:
                        line = re.sub(r'\*(?:start|end)\*[^\d]+', '', line).strip()
                        if not line:
                            continue

                    # Skip potential header/footer junk and noise markers
                    if "DATE DESCRIPTION" in line or \
                       "DATE AMOUNT" in line or \
                       "CHECK NO." in line or \
                       "Account Number" in line or \
                       re.match(r'^[\d\s]+$', line) or \
                       ("through" in line and re.search(r'\d{4}', line)):
                        continue

                    # Clean up trailing "DATE AMOUNT" if it got appended
                    if transactions and transactions[-1]["Description"].endswith(" DATE AMOUNT"):
                         transactions[-1]["Description"] = transactions[-1]["Description"].replace(" DATE AMOUNT", "")


                    # Skip fee explanation text noise
                    if "Excess Transaction Fees" in line or "Your total transactions" in line:
                        continue
                    if "You can use" in line or "Paper checks written" in line or "Deposits and withdrawals" in line:
                        continue
                    if "Monthly Service Fee of either" in line or "sum of the Monthly Service Fee" in line:
                        continue
                    
                    # Prevent duplication of Fee Description
                    if transactions[-1]["Description"].lower() == line.lower():
                        continue
                        
                    # Special case for Monthly Service Fee which often repeats in footer
                    if "Monthly Service Fee" in transactions[-1]["Description"] and "Monthly Service Fee" in line:
                        continue

                    # Skip lines that are just bullet points or special chars
                    if re.match(r'^[\W_]+$', line):
                        continue

                    # Skip tracking ID noise
                    if re.search(r'\d+-[A-Za-z0-9]+', line):
                        continue
                    if re.search(r'[A-Za-z0-9]+-\d+', line) and len(line) > 15:
                        continue
                        
                    # Append to previous transaction description
                    transactions[-1]["Description"] += " " + line

    # Process Checking Summary into Dictionary for main_app validation
    extracted_summary = {}
    for row in checking_summary:
        desc = str(row['Description']).lower()
        amount = row['Amount']
        
        if 'opening' in desc or 'beginning' in desc:
            extracted_summary['Beginning Balance'] = amount
        elif 'closing' in desc or 'ending' in desc:
            extracted_summary['Ending Balance'] = amount
        elif 'deposit' in desc or 'additions' in desc:
            extracted_summary['Deposits'] = abs(amount)
        elif 'withdrawal' in desc or 'debit' in desc:
            if 'Withdrawals' not in extracted_summary:
                extracted_summary['Withdrawals'] = 0.0
            extracted_summary['Withdrawals'] += abs(amount)
        elif 'check' in desc:
            extracted_summary['Checks'] = abs(amount)
        elif 'fee' in desc:
            extracted_summary['Fees'] = abs(amount)

    # Date Processing (Add Year)
    # Determine Year (heuristic: use year from first date if available, else 25)
    year_guess = "25"
    if transactions and 'Date' in transactions[0]:
        first_date_val = str(transactions[0]['Date'])
        if first_date_val.count('/') == 2:
            year_guess = first_date_val.split('/')[-1]
            
    # Update dates in transactions
    final_transactions = []
    for txn in transactions:
        d = txn['Date']
        if d.count('/') == 1:
            d = f"{d}/{year_guess}"
        txn['Date'] = d
        final_transactions.append(txn)
        
    # Update dates in balances and rename Amount to Balance
    final_balances = []
    for bal in balances:
        d = bal['Date']
        if d.count('/') == 1:
            d = f"{d}/{year_guess}"
        
        final_balances.append({
            "Date": d,
            "Balance": bal['Amount'],
            "Page": bal['Page']
        })

    return pd.DataFrame(final_transactions), extracted_summary, pd.DataFrame(final_balances)
