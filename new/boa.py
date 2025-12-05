import streamlit as st
import pdfplumber
import re
import pandas as pd
import io

st.set_page_config(page_title="Bank of America Statement Extractor", layout="wide")

st.title("🏦 Bank of America Statement Extractor")
st.markdown("""
This app extracts transactions from Bank of America PDF statements **without using AI**. 
It handles standard sections, **multi-column check tables**, and **missing check numbers**.
""")

def parse_bank_statement(pdf_file):
    """
    Extracts structured transaction data from the Bank of America PDF statement.
    Also extracts the Account Summary from the first page and Daily Ledger Balances.
    """
    transactions = []
    daily_ledger_entries = []
    current_section = "Unknown"
    extracted_summary = {}
    
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
                            val_str = match.group(1).replace('$', '').replace(',', '')
                            val = float(val_str)
                            extracted_summary[key] = val
                        except ValueError:
                            extracted_summary[key] = 0.0

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
                                daily_ledger_entries.append({
                                    "Date": l_date,
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
            
            progress_bar.progress((idx + 1) / total_pages)
        
        progress_bar.empty()
        status_text.empty()

    return pd.DataFrame(transactions), extracted_summary, pd.DataFrame(daily_ledger_entries)

# --- UI ---
uploaded_file = st.file_uploader("Upload Bank of America PDF Statement", type=['pdf'])

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
                computed_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                computed_withdrawals = df[df['Type'] == 'Withdrawals']['Amount'].sum()
                computed_checks = df[df['Type'] == 'Checks']['Amount'].sum()
                computed_fees = df[df['Type'] == 'Service Fees']['Amount'].sum()
                
                beg_bal = extracted_summary.get("Beginning Balance", 0.0)
                computed_ending = beg_bal + computed_deposits + computed_withdrawals + computed_checks + computed_fees
                
                summary_data = [
                    {"Category": "Beginning Balance", "Extracted": extracted_summary.get("Beginning Balance", 0.0), "Computed": beg_bal, "Difference": 0.0},
                    {"Category": "Deposits/Credits", "Extracted": extracted_summary.get("Deposits/Credits", 0.0), "Computed": computed_deposits, "Difference": extracted_summary.get("Deposits/Credits", 0.0) - computed_deposits},
                    {"Category": "Withdrawals/Debits", "Extracted": extracted_summary.get("Withdrawals/Debits", 0.0), "Computed": computed_withdrawals, "Difference": extracted_summary.get("Withdrawals/Debits", 0.0) - computed_withdrawals},
                    {"Category": "Checks", "Extracted": extracted_summary.get("Checks", 0.0), "Computed": computed_checks, "Difference": extracted_summary.get("Checks", 0.0) - computed_checks},
                    {"Category": "Service Fees", "Extracted": extracted_summary.get("Service Fees", 0.0), "Computed": computed_fees, "Difference": extracted_summary.get("Service Fees", 0.0) - computed_fees},
                    {"Category": "Ending Balance", "Extracted": extracted_summary.get("Ending Balance", 0.0), "Computed": computed_ending, "Difference": extracted_summary.get("Ending Balance", 0.0) - computed_ending},
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
                        except:
                            year = "25"
                    else:
                        year = "25"

                    ledger_df['FullDate'] = ledger_df['Date'] + '/' + year
                    ledger_df['DateTime'] = pd.to_datetime(ledger_df['FullDate'], format='%m/%d/%y', errors='coerce')
                    ledger_df = ledger_df.sort_values('DateTime')
                    
                    # Prepare Transaction Data for Computation
                    df['DateTime'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
                    
                    ledger_analysis = []
                    
                    for idx, row in ledger_df.iterrows():
                        l_date = row['DateTime']
                        l_balance = row['Balance']
                        
                        if pd.isnull(l_date):
                            continue
                            
                        # Calculate computed balance for this date
                        relevant_txns = df[df['DateTime'] <= l_date]
                        txn_sum = relevant_txns['Amount'].sum()
                        computed_bal = beg_bal + txn_sum
                        
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
                col2.metric("Total Withdrawals", f"${computed_withdrawals:,.2f}")
                col3.metric("Total Checks", f"${computed_checks:,.2f}")
                col4.metric("Total Fees", f"${computed_fees:,.2f}")
                
                # Data Grid
                st.subheader("Transaction Details")
                st.dataframe(df, use_container_width=True, height=400)
                
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
                csv = df.to_csv(index=False).encode('utf-8')
                col1.download_button("Download as CSV", csv, "boa_transactions.csv", "text/csv", key='download-csv')
                json_str = df.to_json(orient="records", indent=4)
                col2.download_button("Download as JSON", json_str, "boa_transactions.json", "application/json", key='download-json')
                
            else:
                st.warning("No transactions found.")
                
        except Exception as e:
            st.error(f"Error parsing PDF: {str(e)}")
            st.exception(e)

with st.expander("Regex Logic Explained"):
    st.code(r"""
check_pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+(?:(\d+\*?)\s+)?(\-?[\d,]+\.\d{2})')
ledger_pattern = re.compile(r'(\d{2}/\d{2})\s+((?:-)?[\d,]+\.\d{2})')
    """, language="python")
