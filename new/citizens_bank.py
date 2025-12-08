import streamlit as st
import pdfplumber
import re
import pandas as pd
import io

st.set_page_config(page_title="Citizens Bank Statement Extractor", layout="wide")

st.title("🏦 Citizens Bank Statement Extractor")
st.markdown("""
This app extracts transactions from Citizens Bank PDF statements **without using AI**. 
It handles standard sections, **multi-column check tables**, **Debits**, and **Deposits & Credits**.
""")

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

def parse_bank_statement(pdf_file):
    """
    Extracts structured transaction data from the Citizens Bank PDF statement.
    Also extracts the Account Summary from the first page and Daily Ledger Balances.
    """
    transactions = []
    daily_ledger_entries = []
    current_section = "Unknown"
    extracted_summary = {}
    
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
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_pages = len(pdf.pages)
        status_text.text(f"Processing {total_pages} pages...")
        
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
                            
                            transactions.append({
                                "Date": c_date,
                                "Description": c_desc,
                                "Amount": amount,
                                "Type": current_section,
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
                                daily_ledger_entries.append({
                                    "Date": l_date,
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
                            if clean_line and not date_amount_desc_pattern.match(clean_line):
                                # Don't append if it looks like a new transaction or header
                                if not any(x in clean_line.upper() for x in ['DATE', 'AMOUNT', 'DESCRIPTION', 'TOTAL', 'CONTINUED']):
                                    transactions[last_txn_index]["Description"] += " " + clean_line
            
            progress_bar.progress((idx + 1) / total_pages)
        
        progress_bar.empty()
        status_text.empty()

    return pd.DataFrame(transactions), extracted_summary, pd.DataFrame(daily_ledger_entries)

# --- UI ---
uploaded_file = st.file_uploader("Upload Citizens Bank PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Extracting data from PDF..."):
        try:
            pdf_file = io.BytesIO(uploaded_file.read())
            df, extracted_summary, ledger_df = parse_bank_statement(pdf_file)
            
            if not df.empty:
                # Filtering out 'Unknown' types
                df = df[~df['Type'].isin(['Unknown'])]
                
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # --- Computations for Validation ---
                
                # 1. Summary Computation
                computed_checks = df[df['Type'] == 'Checks']['Amount'].sum()
                computed_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                computed_debits = df[df['Type'] == 'Debits']['Amount'].sum()
                
                prev_bal = extracted_summary.get("Previous Balance", 0.0)
                computed_ending = prev_bal + computed_checks + computed_debits + computed_deposits
                
                summary_data = [
                    {"Category": "Previous Balance", "Extracted": extracted_summary.get("Previous Balance", 0.0), "Computed": prev_bal, "Difference": 0.0},
                    {"Category": "Checks", "Extracted": -extracted_summary.get("Checks", 0.0), "Computed": computed_checks, "Difference": -extracted_summary.get("Checks", 0.0) - computed_checks},
                    {"Category": "Debits", "Extracted": -extracted_summary.get("Debits", 0.0), "Computed": computed_debits, "Difference": -extracted_summary.get("Debits", 0.0) - computed_debits},
                    {"Category": "Deposits/Credits", "Extracted": extracted_summary.get("Deposits/Credits", 0.0), "Computed": computed_deposits, "Difference": extracted_summary.get("Deposits/Credits", 0.0) - computed_deposits},
                    {"Category": "Current Balance", "Extracted": extracted_summary.get("Current Balance", 0.0), "Computed": computed_ending, "Difference": extracted_summary.get("Current Balance", 0.0) - computed_ending},
                ]
                summary_df = pd.DataFrame(summary_data)

                # 2. Ledger Computation
                ledger_analysis_df = pd.DataFrame()
                if not ledger_df.empty:
                    # Determine Year from Transactions
                    if 'Date' in df.columns and not df.empty:
                        first_date = df.iloc[0]['Date']
                        try:
                            year = first_date.split('/')[-1]
                            if len(year) == 2:
                                # Assume 20XX for 2-digit years
                                year = "20" + year if int(year) < 50 else "19" + year
                            else:
                                year = "2025"  # Default
                        except:
                            year = "2025"
                    else:
                        year = "2025"

                    # For Citizens Bank, dates are MM/DD format, need to add year
                    ledger_df['FullDate'] = ledger_df['Date'] + '/' + year[-2:]  # Use last 2 digits
                    ledger_df['DateTime'] = pd.to_datetime(ledger_df['FullDate'], format='%m/%d/%y', errors='coerce')
                    ledger_df = ledger_df.sort_values('DateTime')
                    
                    # Prepare Transaction Data for Computation
                    df['FullDate'] = df['Date'] + '/' + year[-2:]
                    df['DateTime'] = pd.to_datetime(df['FullDate'], format='%m/%d/%y', errors='coerce')
                    
                    ledger_analysis = []
                    
                    for idx, row in ledger_df.iterrows():
                        l_date = row['DateTime']
                        l_balance = row['Balance']
                        
                        if pd.isnull(l_date):
                            continue
                            
                        # Calculate computed balance for this date
                        relevant_txns = df[df['DateTime'] <= l_date]
                        txn_sum = relevant_txns['Amount'].sum()
                        computed_bal = prev_bal + txn_sum
                        
                        diff = l_balance - computed_bal
                        
                        ledger_analysis.append({
                            "Date": row['Date'],
                            "Extracted Balance": l_balance,
                            "Computed Balance": computed_bal,
                            "Difference": diff
                        })
                    
                    ledger_analysis_df = pd.DataFrame(ledger_analysis)

                # --- Validation Check ---
                summary_diffs = [d['Category'] for d in summary_data if abs(d['Difference']) > 0.01]
                
                ledger_diffs = []
                if not ledger_analysis_df.empty:
                    ledger_diffs = ledger_analysis_df[abs(ledger_analysis_df['Difference']) > 0.01]['Date'].tolist()
                
                if not summary_diffs and not ledger_diffs:
                    st.success("✅ PASSED: All extracted values match computed balances.")
                else:
                    error_msg = "❌ FAILED: Discrepancies found."
                    if summary_diffs:
                        error_msg += f"\n\n**Summary Discrepancies:** {', '.join(summary_diffs)}"
                    if ledger_diffs:
                        error_msg += f"\n\n**Daily Ledger Discrepancies (Dates):** {', '.join(str(d) for d in ledger_diffs)}"
                    st.error(error_msg)
                
                def format_currency(x):
                    return "${:,.2f}".format(x)

                # --- Account Summary Table ---
                st.subheader("Account Summary Comparison")
                display_df = summary_df.copy()
                display_df['Extracted'] = display_df['Extracted'].apply(format_currency)
                display_df['Computed'] = display_df['Computed'].apply(format_currency)
                # Difference shown as raw number
                st.table(display_df)
                
                # --- Transaction Metrics ---
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Total Deposits", f"${computed_deposits:,.2f}")
                col2.metric("Total Debits", f"${abs(computed_debits):,.2f}")
                col3.metric("Total Checks", f"${abs(computed_checks):,.2f}")
                col4.metric("Net Change", f"${(computed_deposits + computed_debits + computed_checks):,.2f}")
                
                # Data Grid
                st.subheader("Transaction Details")
                # Ensure DateTime column exists and sort
                if 'DateTime' not in df.columns:
                    if 'Date' in df.columns:
                        year = "2025"  # Default year
                        df['FullDate'] = df['Date'] + '/' + year[-2:]
                        df['DateTime'] = pd.to_datetime(df['FullDate'], format='%m/%d/%y', errors='coerce')
                
                df_sorted = df.sort_values('DateTime', ascending=True).reset_index(drop=True)
                # Drop helper columns if not needed for display
                display_txns = df_sorted.drop(columns=['DateTime', 'FullDate'], errors='ignore')
                
                st.dataframe(display_txns, use_container_width=True, height=400)
                
                # --- Daily Ledger Analysis ---
                if not ledger_analysis_df.empty:
                    st.subheader("Daily Ledger Balances Analysis")
                    
                    # Format for display
                    display_ledger = ledger_analysis_df.copy()
                    display_ledger['Extracted Balance'] = display_ledger['Extracted Balance'].apply(format_currency)
                    display_ledger['Computed Balance'] = display_ledger['Computed Balance'].apply(format_currency)
                    # Difference shown as raw number
                    st.table(display_ledger)
                
                # Download Buttons
                col1, col2 = st.columns(2)
                # Use the sorted DataFrame for downloads
                csv = display_txns.to_csv(index=False).encode('utf-8')
                col1.download_button("Download as CSV", csv, "citizens_bank_transactions.csv", "text/csv", key='download-csv')
                
                json_str = display_txns.to_json(orient="records", indent=4)
                col2.download_button("Download as JSON", json_str, "citizens_bank_transactions.json", "application/json", key='download-json')
                
            else:
                st.warning("No transactions found.")
                
        except Exception as e:
            st.error(f"Error parsing PDF: {str(e)}")
            st.exception(e)

with st.expander("How It Works"):
    st.markdown("""
    ### Extraction Logic
    
    This script extracts data from Citizens Bank statements by:
    
    1. **Checks Section**: Matches patterns like `3252 165.00 04/03` (Check# Amount Date)
    2. **Debits Section**: Matches patterns like `04/01 1,530.00 Description` (Date Amount Description)
    3. **Deposits Section**: Matches patterns like `04/01 900.00 Description` (Date Amount Description)
    4. **Daily Balance**: Extracts date-balance pairs from the daily balance table
    
    The script automatically:
    - Detects section headers to categorize transactions
    - Handles multi-line descriptions
    - Validates extracted totals against computed values
    - Compares daily balances with transaction-based calculations
    """)
