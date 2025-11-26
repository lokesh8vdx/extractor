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
    """
    transactions = []
    current_section = "Unknown"
    
    # 1. General Pattern: Date at start, Description in middle, Amount at end
    date_start_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.*?)(\-?[\d,]+\.\d{2})$')
    
    # 2. Specific Check Pattern: Date | Optional Check # | Amount
    # Explanation:
    # (\d{2}/\d{2}/\d{2})       -> Capture Group 1: Date (MM/DD/YY)
    # \s+                       -> Required whitespace
    # (?:(\d+\*?)\s+)?          -> Non-capturing optional group for Check #:
    #     (\d+\*?)              -> Capture Group 2: Digits and optional '*' (e.g., "1331*")
    #     \s+                   -> Space after check number
    # (\-?[\d,]+\.\d{2})        -> Capture Group 3: Amount (e.g., "-366.00" or "2,000.00")
    check_pattern = re.compile(r'(\d{2}/\d{2}/\d{2})\s+(?:(\d+\*?)\s+)?(\-?[\d,]+\.\d{2})')
    
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
            
            lines = text.split('\n')
            
            for line in lines:
                # --- 1. Detect Section Change ---
                section_found = False
                for key, section_name in section_keywords.items():
                    if key in line:
                        current_section = section_name
                        section_found = True
                        break
                
                if section_found or current_section == "Ignore":
                    continue

                # --- 2. Parse Based on Section Type ---
                
                # LOGIC FOR CHECKS (Multi-Column & Optional Check #)
                if current_section == "Checks":
                    # findall returns a list of tuples: 
                    # e.g. [('04/08/25', '', '-366.00'), ('04/10/25', '120', '-2,000.00')]
                    matches = check_pattern.findall(line)
                    
                    if matches:
                        for m in matches:
                            c_date = m[0]
                            c_num = m[1]
                            c_amt_str = m[2].replace(',', '')
                            
                            # Handle description based on whether Check # exists
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
            
            # Update progress
            progress_bar.progress((idx + 1) / total_pages)
        
        progress_bar.empty()
        status_text.empty()

    return pd.DataFrame(transactions)

# --- UI ---
uploaded_file = st.file_uploader("Upload Bank of America PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Extracting data from PDF..."):
        try:
            # Create a file-like object from uploaded file
            pdf_file = io.BytesIO(uploaded_file.read())
            df = parse_bank_statement(pdf_file)
            
            # Filtering out 'Unknown' and 'Ignore' types
            df = df[~df['Type'].isin(['Unknown', 'Ignore'])]
            
            if not df.empty:
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # Show Summary
                col1, col2, col3, col4 = st.columns(4)
                
                # Checks are usually negative in statement data, but we sum absolute for display
                total_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                total_withdrawals = df[df['Type'] == 'Withdrawals']['Amount'].sum()
                total_checks = df[df['Type'] == 'Checks']['Amount'].sum()
                total_fees = df[df['Type'] == 'Service Fees']['Amount'].sum()
                
                col1.metric("Total Deposits", f"${total_deposits:,.2f}")
                col2.metric("Total Withdrawals", f"${total_withdrawals:,.2f}")
                col3.metric("Total Checks", f"${total_checks:,.2f}")
                col4.metric("Total Fees", f"${total_fees:,.2f}")
                
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