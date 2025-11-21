import streamlit as st
import pdfplumber
import re
import pandas as pd
import io

st.set_page_config(page_title="Bank of America Statement Extractor", layout="wide")

st.title("🏦 Bank of America Statement Extractor")
st.markdown("""
This app extracts transactions from Bank of America PDF statements **without using AI**. 
It uses `pdfplumber` to extract text and Regex to parse dates, descriptions, and amounts.
""")

def parse_bank_statement(pdf_file):
    """
    Extracts structured transaction data from the Bank of America PDF statement.
    """
    transactions = []
    current_section = "Unknown"
    
    # Regex patterns specific to this statement format
    # Matches lines starting with a date like 04/01/25
    date_start_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.*?)(\-?[\d,]+\.\d{2})$')
    
    # Sections keywords to switch context
    section_keywords = {
        "Deposits and other credits": "Deposits",
        "Withdrawals and other debits": "Withdrawals",
        "Checks": "Checks",
        "Service fees": "Service Fees"
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
                # 1. Detect Section Change
                for key, section_name in section_keywords.items():
                    if key in line:
                        current_section = section_name
                        # Stop processing this line as a transaction
                        break 
                
                # 2. Parse Transaction Lines
                # We look for lines that start with a Date (MM/DD/YY)
                match = date_start_pattern.match(line)
                
                if match:
                    date = match.group(1)
                    description = match.group(2).strip()
                    amount_str = match.group(3).replace(',', '')
                    
                    try:
                        amount = float(amount_str)
                    except ValueError:
                        amount = 0.0

                    # Checks often have a check number in the description column
                    # Logic to clean up check numbers if needed can go here
                    
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
            
            # Filtering out the 'Unknown' section which usually captures the summary table
            df = df[df['Type'] != 'Unknown']
            
            if not df.empty:
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # Show Summary
                col1, col2, col3, col4 = st.columns(4)
                
                total_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                total_withdrawals = abs(df[df['Type'] == 'Withdrawals']['Amount'].sum())
                total_checks = abs(df[df['Type'] == 'Checks']['Amount'].sum())
                total_fees = abs(df[df['Type'] == 'Service Fees']['Amount'].sum())
                
                col1.metric("Total Deposits", f"${total_deposits:,.2f}")
                col2.metric("Total Withdrawals", f"${total_withdrawals:,.2f}")
                col3.metric("Total Checks", f"${total_checks:,.2f}")
                col4.metric("Total Fees", f"${total_fees:,.2f}")
                
                # Net Change
                net_change = total_deposits - total_withdrawals - total_checks - total_fees
                st.metric("Net Change", f"${net_change:,.2f}")
                
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

with st.expander("How this works (The 'No-AI' Logic)"):
    st.code("""
# The Logic Pattern (Regex)
# We look for:
# 1. A date at the start (04/01/25)
# 2. Any text in the middle (Description)
# 3. A monetary number at the end (-1,260.68)

date_start_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.*?)(\-?[\d,]+\.\d{2})$')

# Section Detection
# The parser identifies section headers like:
# - "Deposits and other credits"
# - "Withdrawals and other debits"
# - "Checks"
# - "Service fees"
# 
# Transactions are categorized based on which section they appear in.
    """, language="python")