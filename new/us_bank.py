import streamlit as st
import pdfplumber
import re
import pandas as pd
import io
from datetime import datetime

st.set_page_config(page_title="U.S. Bank Statement Extractor", layout="wide")

st.title("🏦 U.S. Bank Statement Extractor")
st.markdown("""
This app extracts transactions from U.S. Bank PDF statements **without using AI**. 
It handles standard sections: **Customer Deposits**, **Other Deposits**, **Card Deposits**, **Card Withdrawals**, **Other Withdrawals**, and **Checks Paid**.
""")

def parse_bank_statement(pdf_file):
    """
    Extracts structured transaction data from the U.S. Bank PDF statement.
    Also extracts the Account Summary and Balance Summary.
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
    # Example: "Mar 4 8315172576 7,500.00" (can have two per line)
    # Format: Date Ref Number Amount (no description field)
    customer_deposit_pattern = re.compile(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+([A-Z0-9_\-]+)\s+([\d,]+\.\d{2})')
    
    # 1. Pattern for Other Deposits: Date Description [Ref Number] [Amount with optional $]
    # Examples: 
    #   "Apr 1 Visa Direct Earnin CEAGF_B 4603312336 $ 150.00"
    #   "Apr 2 Real Time Payment Credit From Jamal Pompey 500.00"
    #   "Apr 3 Mobile Banking Transfer From Account 167300030308 20.00"
    deposit_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})$')
    
    # Pattern for Card Deposits: Date Description [Ref Number] Amount
    # Example: "Mar 7 ATM Deposit US BANK MOHAWK N SPRINGFIELD OR $ 221.00"
    card_deposit_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})$')
    
    # 2. Pattern for Card Withdrawals: Date Description Ref Number Amount
    # Example: "Apr 4 Debit Purchase - VISA On 040325 877-2644218 FL 4057611337 $ 100.00-"
    card_withdrawal_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})-?$')
    
    # 3. Pattern for Other Withdrawals: Date Description [Ref Number] Amount
    # Example: "Apr 1 Mobile Banking Transfer To Account 167300030308 $ 40.00-"
    other_withdrawal_pattern = re.compile(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+(.+?)\s+(?:\$\s+)?([\d,]+\.\d{2})-?$')
    
    # 4. Pattern for Checks: Check Number Date Ref Number Amount
    # Example: "2410 Apr 7 8014176219 346.50"
    # Can have two checks per line: "2410 Apr 7 8014176219 346.50 2421 Apr 11 8913780785 164.82"
    # Check numbers may have asterisks: "2405* Apr 15 8313903782 89.00"
    # Check numbers must be at least 3 digits to avoid matching "00" from amounts like "7,500.00"
    # Or 2 digits with asterisk (e.g., "24*")
    check_pattern = re.compile(r'\b(\d{3,}\*?|\d{2}\*)\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2})\s+([A-Z0-9_\-]+)\s+([\d,]+\.\d{2})')
    
    # 5. Pattern for Balance Summary: Date Ending Balance
    # Example: "Apr 1 498.79-" or multiple columns: "Mar 3 707.85 Mar 12 12.48"
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
        r'^Number\s+Date\s+Ref\s+Number\s+Amount',  # Customer Deposits header
    ]
    ignore_regex = re.compile('|'.join(ignore_patterns), re.IGNORECASE)
    
    # Summary Patterns for Account Summary section
    # Try multiple patterns for each category to handle format variations
    summary_patterns = {
        "Beginning Balance": [
            re.compile(r"Beginning Balance on .*?\$\s+((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"Beginning Balance.*?((?:-)?[\d,]+\.\d{2})")
        ],
        "Customer Deposits": [
            re.compile(r"Total Customer Deposits\s+\$\s*((?:-)?[\d,]+\.\d{2})"),
            re.compile(r"^Customer Deposits\s+\d+\s+((?:-)?[\d,]+\.\d{2})$"),  # Summary line: "Customer Deposits 3 11,055.00"
            re.compile(r"^Customer Deposits\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})$"),  # With dollar sign
        ],
        "Other Deposits": [
            re.compile(r"Total Other Deposits\s+\$\s*((?:-)?[\d,]+\.\d{2})"),  # Try "Total Other Deposits" first
            re.compile(r"^Other Deposits\s+\d+\s+((?:-)?[\d,]+\.\d{2})$"),  # Summary line: "Other Deposits 14 41,904.83"
            re.compile(r"^Other Deposits\s+\d+\s+\$\s*((?:-)?[\d,]+\.\d{2})$"),  # With dollar sign
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
    
    with pdfplumber.open(pdf_file) as pdf:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_pages = len(pdf.pages)
        status_text.text(f"Processing {total_pages} pages...")
        
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
                        # We've reached the transaction details, stop looking
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
                    # Use findall to get all customer deposits from a line (handles two-column format)
                    matches = customer_deposit_pattern.findall(line.strip())
                    if matches:
                        for match in matches:
                            month_abbr = match[0]
                            day = match[1].zfill(2)
                            ref_number = match[2]
                            amount_str = match[3].replace(',', '')
                            
                            # Convert to standard date format
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
                        
                        # Try to extract ref number from description (usually at the end)
                        # Ref numbers are typically alphanumeric sequences
                        ref_match = re.search(r'\s+([A-Z0-9_\-]{8,})$', description_and_ref)
                        if ref_match:
                            ref_number = ref_match.group(1)
                            description = description_and_ref[:description_and_ref.rfind(ref_number)].strip()
                        else:
                            # Check if last part looks like a ref number
                            parts = description_and_ref.split()
                            if len(parts) > 1 and re.match(r'^[A-Z0-9_\-]{6,}$', parts[-1]):
                                ref_number = parts[-1]
                                description = ' '.join(parts[:-1])
                            else:
                                ref_number = ""
                                description = description_and_ref
                        
                        # Convert to standard date format
                        month_num = month_map.get(month_abbr, '01')
                        if statement_year:
                            date = f"{month_num}/{day}/{statement_year[-2:]}"
                        else:
                            date = f"{month_num}/{day}/25"  # Default year
                        
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
                        # Handle multi-line descriptions (e.g., "On 04/02/25 121000248P1BZWFC62967875074")
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not clean_line.startswith('$') and not re.match(r'^Total\s+', clean_line, re.IGNORECASE):
                                # Check if it's a continuation line
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
                        
                        # Convert to standard date format
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
                        # Handle multi-line descriptions
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            # Check ignore pattern again if needed, but main loop handles it.
                            # Specifically handle Serial No. lines
                            if clean_line and not clean_line.startswith('$') and not re.match(r'^Total\s+', clean_line, re.IGNORECASE):
                                if clean_line.startswith('Serial No.'):
                                    # If we haven't set a ref number yet, use this
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
                        
                        # Try to extract ref number from description (usually at the end)
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
                        
                        # Convert to standard date format
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
                        # Handle multi-line descriptions
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
                        
                        # Try to extract ref number from description
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
                        
                        # Convert to standard date format
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
                        # Handle multi-line descriptions
                        if last_txn_index is not None:
                            clean_line = line.strip()
                            if clean_line and not clean_line.startswith('$') and not re.match(r'^Total\s+', clean_line, re.IGNORECASE):
                                # Check if it's a continuation line
                                if clean_line.startswith('REF='):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                                elif not re.match(r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d', clean_line):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
                
                # LOGIC FOR CHECKS PAID
                elif current_section == "Checks Paid":
                    # Use findall to get all checks from a line (handles two-column format)
                    matches = check_pattern.findall(line.strip())
                    if matches:
                        for match in matches:
                            check_num = match[0]
                            month_abbr = match[1]
                            day = match[2].zfill(2)
                            ref_number = match[3]
                            amount_str = match[4].replace(',', '')
                            
                            # Convert to standard date format
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
                    # Skip lines that match check pattern (check entries shouldn't be in balance summary)
                    # Check if line starts with a check number pattern (3+ digits followed by month abbreviation)
                    # This catches check entries even if they don't have a ref number
                    stripped_line = line.strip()
                    if check_pattern.search(stripped_line) or re.match(r'^\d{3,}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}', stripped_line):
                        continue
                    
                    matches = balance_pattern.findall(line)
                    if matches:
                        for match in matches:
                            month_abbr = match[0]
                            day = match[1].zfill(2)
                            balance_str = match[2].replace(',', '')
                            
                            # Handle trailing negative sign
                            if balance_str.endswith('-'):
                                balance_str = '-' + balance_str[:-1]
                                
                            # Convert to standard date format
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
            
            progress_bar.progress((idx + 1) / total_pages)
        
        progress_bar.empty()
        status_text.empty()
    
    return pd.DataFrame(transactions), extracted_summary, pd.DataFrame(balance_summary_entries)

# --- UI ---
uploaded_file = st.file_uploader("Upload U.S. Bank PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Extracting data from PDF..."):
        try:
            pdf_file = io.BytesIO(uploaded_file.read())
            df, extracted_summary, balance_df = parse_bank_statement(pdf_file)
            
            if not df.empty:
                # Filter out 'Unknown' types
                df = df[~df['Type'].isin(['Unknown'])]
                
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # --- Computations for Validation ---
                
                # 1. Summary Computation
                computed_customer_deposits = df[df['Type'] == 'Customer Deposits']['Amount'].sum()
                computed_other_deposits = df[df['Type'] == 'Other Deposits']['Amount'].sum()
                computed_card_deposits = df[df['Type'] == 'Card Deposits']['Amount'].sum()
                computed_card_withdrawals = abs(df[df['Type'] == 'Card Withdrawals']['Amount'].sum())
                computed_other_withdrawals = abs(df[df['Type'] == 'Other Withdrawals']['Amount'].sum())
                computed_checks = abs(df[df['Type'] == 'Checks Paid']['Amount'].sum())
                
                beg_bal = extracted_summary.get("Beginning Balance", 0.0)
                computed_ending = beg_bal + computed_customer_deposits + computed_other_deposits + computed_card_deposits - computed_card_withdrawals - computed_other_withdrawals - computed_checks
                
                summary_data = [
                    {"Category": "Beginning Balance", "Extracted": extracted_summary.get("Beginning Balance", 0.0), 
                     "Computed": beg_bal, "Difference": 0.0},
                    {"Category": "Customer Deposits", "Extracted": extracted_summary.get("Customer Deposits", 0.0), 
                     "Computed": computed_customer_deposits, "Difference": extracted_summary.get("Customer Deposits", 0.0) - computed_customer_deposits},
                    {"Category": "Other Deposits", "Extracted": extracted_summary.get("Other Deposits", 0.0), 
                     "Computed": computed_other_deposits, "Difference": extracted_summary.get("Other Deposits", 0.0) - computed_other_deposits},
                    {"Category": "Card Deposits", "Extracted": extracted_summary.get("Card Deposits", 0.0), 
                     "Computed": computed_card_deposits, "Difference": extracted_summary.get("Card Deposits", 0.0) - computed_card_deposits},
                    {"Category": "Card Withdrawals", "Extracted": abs(extracted_summary.get("Card Withdrawals", 0.0)), 
                     "Computed": computed_card_withdrawals, "Difference": abs(extracted_summary.get("Card Withdrawals", 0.0)) - computed_card_withdrawals},
                    {"Category": "Other Withdrawals", "Extracted": abs(extracted_summary.get("Other Withdrawals", 0.0)), 
                     "Computed": computed_other_withdrawals, "Difference": abs(extracted_summary.get("Other Withdrawals", 0.0)) - computed_other_withdrawals},
                    {"Category": "Checks Paid", "Extracted": abs(extracted_summary.get("Checks Paid", 0.0)), 
                     "Computed": computed_checks, "Difference": abs(extracted_summary.get("Checks Paid", 0.0)) - computed_checks},
                    {"Category": "Ending Balance", "Extracted": extracted_summary.get("Ending Balance", 0.0), 
                     "Computed": computed_ending, "Difference": extracted_summary.get("Ending Balance", 0.0) - computed_ending},
                ]
                summary_df = pd.DataFrame(summary_data)
                
                # --- Compute Balance Summary Differences ---
                balance_summary_diffs = []
                if not balance_df.empty:
                    # Compute balance summary from transactions
                    # Convert transaction dates to datetime for proper sorting
                    df_with_dt = df.copy()
                    df_with_dt['DateTime'] = pd.to_datetime(df_with_dt['Date'], format='%m/%d/%y', errors='coerce')
                    df_with_dt = df_with_dt.sort_values('DateTime', ascending=True).reset_index(drop=True)
                    
                    # Compute running balance for each date
                    balance_df['DateTime'] = pd.to_datetime(balance_df['Date'], format='%m/%d/%y', errors='coerce')
                    balance_df = balance_df.sort_values('DateTime', ascending=True).reset_index(drop=True)
                    
                    # Create a dictionary to store computed balances by date
                    computed_balances = {}
                    current_balance = beg_bal
                    
                    # Group transactions by date and compute running balance
                    for date_str in sorted(df_with_dt['Date'].unique()):
                        date_dt = pd.to_datetime(date_str, format='%m/%d/%y', errors='coerce')
                        if pd.isna(date_dt):
                            continue
                        
                        # Sum all transactions for this date
                        day_transactions = df_with_dt[df_with_dt['Date'] == date_str]
                        day_total = day_transactions['Amount'].sum()
                        current_balance += day_total
                        
                        # Store the balance for this date
                        computed_balances[date_str] = current_balance
                    
                    # For each extracted balance date, find the computed balance
                    # Use the balance at the end of that day
                    balance_df['Computed'] = balance_df['Date'].apply(
                        lambda x: computed_balances.get(x, None)
                    )
                    
                    # If computed balance is None for a date, calculate it from transactions up to that date
                    for idx, row in balance_df.iterrows():
                        if pd.isna(row['Computed']):
                            # Calculate balance up to this date
                            date_dt = row['DateTime']
                            transactions_up_to_date = df_with_dt[df_with_dt['DateTime'] <= date_dt]
                            computed_balance = beg_bal + transactions_up_to_date['Amount'].sum()
                            balance_df.at[idx, 'Computed'] = computed_balance
                    
                    # Calculate difference
                    balance_df['Difference'] = balance_df['Balance'] - balance_df['Computed']
                    
                    # Check for balance summary differences
                    balance_diffs = balance_df[abs(balance_df['Difference']) > 0.01]
                    if not balance_diffs.empty:
                        balance_summary_diffs = balance_diffs['Date'].tolist()
                
                # --- Validation Check ---
                summary_diffs = [d['Category'] for d in summary_data if abs(d['Difference']) > 0.01]
                
                if not summary_diffs and not balance_summary_diffs:
                    st.success("✅ PASSED: All extracted values match computed balances (Account Summary and Daily Balance Summary).")
                else:
                    error_msg = "❌ FAILED: Discrepancies found."
                    if summary_diffs:
                        error_msg += f"\n\n**Account Summary Discrepancies:** {', '.join(summary_diffs)}"
                    if balance_summary_diffs:
                        error_msg += f"\n\n**Daily Balance Summary Discrepancies:** {len(balance_summary_diffs)} date(s) with differences"
                    st.error(error_msg)
                
                def format_currency(x):
                    # Handle negative zero case
                    if abs(x) < 0.005:  # Within rounding tolerance
                        return "$0.00"
                    return "${:,.2f}".format(x)
                
                # --- Account Summary Table ---
                st.subheader("Account Summary Comparison")
                display_df = summary_df.copy()
                display_df['Extracted'] = display_df['Extracted'].apply(format_currency)
                display_df['Computed'] = display_df['Computed'].apply(format_currency)
                # Format difference as number, handling negative zero
                def format_difference_summary(x):
                    # Handle negative zero case
                    if abs(x) < 0.005:  # Within rounding tolerance
                        return "0.00"
                    return f"{x:,.2f}"
                display_df['Difference'] = display_df['Difference'].apply(format_difference_summary)
                st.table(display_df)
                
                # --- Transaction Metrics ---
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                col1.metric("Customer Deposits", f"${computed_customer_deposits:,.2f}")
                col2.metric("Other Deposits", f"${computed_other_deposits:,.2f}")
                col3.metric("Card Deposits", f"${computed_card_deposits:,.2f}")
                col4.metric("Card Withdrawals", f"${computed_card_withdrawals:,.2f}")
                col5.metric("Other Withdrawals", f"${computed_other_withdrawals:,.2f}")
                col6.metric("Checks Paid", f"${computed_checks:,.2f}")
                
                # Data Grid
                st.subheader("Transaction Details")
                # Sort by extraction sequence (order in which transactions were extracted from PDF)
                if 'Extraction_Seq' in df.columns:
                    df_sorted = df.sort_values('Extraction_Seq', ascending=True).reset_index(drop=True)
                else:
                    # Fallback to date sorting if Extraction_Seq is missing
                    if 'DateTime' not in df.columns:
                        if 'Date' in df.columns:
                            df['DateTime'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
                    df_sorted = df.sort_values('DateTime', ascending=True).reset_index(drop=True)
                    df_sorted = df_sorted.drop(columns=['DateTime'], errors='ignore')
                
                # Drop helper column if not needed for display
                display_txns = df_sorted.drop(columns=['Extraction_Seq'], errors='ignore')
                
                st.dataframe(display_txns, use_container_width=True, height=400)
                
                # --- Balance Summary ---
                if not balance_df.empty:
                    st.subheader("Daily Balance Summary Comparison")
                    balance_display = balance_df.drop(columns=['DateTime'], errors='ignore').copy()
                    balance_display['Balance'] = balance_display['Balance'].apply(format_currency)
                    balance_display['Computed'] = balance_display['Computed'].apply(format_currency)
                    # Format difference as number (not currency) for display, handling negative zero
                    def format_difference(x):
                        # Handle negative zero case
                        if abs(x) < 0.005:  # Within rounding tolerance
                            return "0.00"
                        return f"{x:,.2f}"
                    balance_display['Difference'] = balance_display['Difference'].apply(format_difference)
                    st.table(balance_display)
                
                # Download Buttons
                col1, col2 = st.columns(2)
                # Use the sorted DataFrame for downloads
                csv = display_txns.to_csv(index=False).encode('utf-8')
                col1.download_button("Download as CSV", csv, "us_bank_transactions.csv", "text/csv", key='download-csv')
                
                json_str = display_txns.to_json(orient="records", indent=4)
                col2.download_button("Download as JSON", json_str, "us_bank_transactions.json", "application/json", key='download-json')
                
            else:
                st.warning("No transactions found.")
                
        except Exception as e:
            st.error(f"Error parsing PDF: {str(e)}")
            st.exception(e)

with st.expander("How It Works"):
    st.markdown("""
    This extractor uses regex patterns to identify different transaction types:
    
    1. **Customer Deposits**: Matches date, reference number, and amount (no description field)
    2. **Other Deposits**: Matches date, description, reference number, and amount
    3. **Card Deposits**: Matches ATM and card-based deposits
    4. **Card Withdrawals**: Matches debit card transactions with reference numbers
    5. **Other Withdrawals**: Matches electronic withdrawals and transfers
    6. **Checks Paid**: Matches check number, date, reference number, and amount
    7. **Balance Summary**: Extracts daily ending balances
    
    The script validates extracted totals against the Account Summary section to ensure accuracy.
    """)
