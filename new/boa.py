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
    Also extracts the Account Summary from the first page.
    """
    transactions = []
    current_section = "Unknown"
    extracted_summary = {}
    
    # 1. General Pattern: Date at start, Description in middle, Amount at end
    date_start_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.*?)(\-?[\d,]+\.\d{2})$')
    
    # 2. Specific Check Pattern: Date | Optional Check # | Amount
    check_pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+(?:(\d+\*?)\s+)?(\-?[\d,]+\.\d{2})')
    
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
        r'^Note\s+your\s+Ending\s+Balance'
    ]
    ignore_regex = re.compile('|'.join(ignore_patterns), re.IGNORECASE)
    
    # Summary Patterns
    # Updated to handle potential negative signs and optional dollar signs for all fields
    # (?:-)? matches an optional negative sign
    # \$? matches an optional dollar sign
    # [\d,]+\.\d{2} matches the amount
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
        "Daily ledger balances": "Ignore" # Stop parsing when we hit the footer summary
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
                    # Check if the line *starts with* or acts as a clear header to avoid false positives in descriptions
                    # Original code was 'if key in line'. Kept simple but added length check to avoid partial matches if needed.
                    # However, strictly sticking to original logic for section detection to avoid regressions, 
                    # but we must ensure we don't append section headers to descriptions.
                    if key in line:
                        current_section = section_name
                        section_found = True
                        last_txn_index = None # Reset context
                        break
                
                if section_found or current_section == "Ignore":
                    continue
                
                # Check for Footer/Noise lines
                if ignore_regex.search(line):
                    # If we hit a footer/header/noise line, assume the previous transaction's 
                    # multi-line description has ended.
                    last_txn_index = None 
                    continue

                # --- 2. Parse Based on Section Type ---
                
                # LOGIC FOR CHECKS (Multi-Column & Optional Check #)
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
                        # Reset index because checks don't typically have continuation lines in this layout
                        last_txn_index = None 
                            
                # LOGIC FOR DEPOSITS, WITHDRAWALS, FEES (Single Column / General)
                else:
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
                        # Track this transaction for potential multi-line descriptions
                        last_txn_index = len(transactions) - 1
                    
                    else:
                        # --- Handle Multi-line Descriptions ---
                        # If it's not a new transaction (no date match), 
                        # check if we should append this line to the previous transaction.
                        if last_txn_index is not None and current_section in ["Deposits", "Withdrawals", "Service Fees"]:
                            clean_line = line.strip()
                            if clean_line:
                                transactions[last_txn_index]["Description"] += " " + clean_line
            
            # Update progress
            progress_bar.progress((idx + 1) / total_pages)
        
        progress_bar.empty()
        status_text.empty()

    return pd.DataFrame(transactions), extracted_summary

# --- UI ---
uploaded_file = st.file_uploader("Upload Bank of America PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Extracting data from PDF..."):
        try:
            # Create a file-like object from uploaded file
            pdf_file = io.BytesIO(uploaded_file.read())
            df, extracted_summary = parse_bank_statement(pdf_file)
            
            # Filtering out 'Unknown' and 'Ignore' types
            df = df[~df['Type'].isin(['Unknown', 'Ignore'])]
            
            if not df.empty:
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # --- Account Summary Table ---
                st.subheader("Account Summary Comparison")
                
                # Calculate Computed Values
                computed_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                computed_withdrawals = df[df['Type'] == 'Withdrawals']['Amount'].sum()
                computed_checks = df[df['Type'] == 'Checks']['Amount'].sum()
                computed_fees = df[df['Type'] == 'Service Fees']['Amount'].sum()
                
                # Beginning balance is not computed from transactions, so we take extracted or 0
                beg_bal = extracted_summary.get("Beginning Balance", 0.0)
                
                # Compute Ending Balance
                # Note: Withdrawals, Checks, Fees are usually negative in the DF if parsed correctly as negative numbers.
                # Based on the regex (r'(\-?[\d,]+\.\d{2})'), they capture the negative sign.
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
                
                # Format columns for display
                def format_currency(x):
                    return "${:,.2f}".format(x)
                
                display_df = summary_df.copy()
                display_df['Extracted'] = display_df['Extracted'].apply(format_currency)
                display_df['Computed'] = display_df['Computed'].apply(format_currency)
                display_df['Difference'] = display_df['Difference'].apply(format_currency)
                
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
                
                # Download Buttons
                col1, col2 = st.columns(2)
                
                # CSV Download
                csv = df.to_csv(index=False).encode('utf-8')
                col1.download_button(
                    "Download as CSV",
                    csv,
                    "bank_of_america_statement.csv",
                    "text/csv",
                    key='download-csv'
                )
                
                # JSON Download
                json_str = df.to_json(orient="records", indent=4)
                col2.download_button(
                    "Download as JSON",
                    json_str,
                    "bank_of_america_statement.json",
                    "application/json",
                    key='download-json'
                )
            else:
                st.warning("No transactions found. Ensure this is a standard Bank of America PDF statement.")
                
        except Exception as e:
            st.error(f"Error parsing PDF: {str(e)}")
            st.exception(e)

with st.expander("Regex Logic Explained"):
    st.code(r"""
# The Updated Check Pattern
# (?: ... )? means the group inside is optional
# \d+\*? matches the check number (digits) plus an optional asterisk

check_pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+(?:(\d+\*?)\s+)?(\-?[\d,]+\.\d{2})')

# Example Match 1 (With Check #): "04/10/25 120 -2,000.00"
# Group 1 (Date): "04/10/25"
# Group 2 (Check): "120"
# Group 3 (Amount): "-2,000.00"

# Example Match 2 (No Check #): "04/08/25 -366.00"
# Group 1 (Date): "04/08/25"
# Group 2 (Check): "" (Empty)
# Group 3 (Amount): "-366.00"
    """, language="python")
