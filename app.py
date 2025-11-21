import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

st.set_page_config(page_title="No-AI Bank Extractor", layout="wide")

st.title("📄 Bank Statement Extractor (Rule-Based)")
st.markdown("""
This app extracts transactions from Chase bank statements **without using AI**. 
It uses `pdfplumber` to spatially analyze the text layout and Regex to parse dates and amounts.
""")

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

def extract_chase_transactions(pdf_file):
    transactions = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            # Extract text with layout preservation
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            lines = text.split('\n')
            
            # Chase Statement Logic
            # We look for lines that start with a date pattern like MM/DD
            # Regex: Start of line (^), 2 digits, slash, 2 digits
            date_pattern = re.compile(r'^(\d{2}/\d{2})\s+(.*)\s+(-?\$?[\d,]+\.\d{2})$')
            
            current_section = None
            
            for line in lines:
                line = line.strip()
                
                # Detect Sections to categorize transactions
                if "DEPOSITS AND ADDITIONS" in line:
                    current_section = "Deposit"
                    continue
                elif "ATM & DEBIT CARD WITHDRAWALS" in line:
                    current_section = "Withdrawal"
                    continue
                elif "ELECTRONIC WITHDRAWALS" in line:
                    current_section = "Withdrawal"
                    continue
                elif "FEES" in line:
                    current_section = "Fee"
                    continue
                
                # Skip irrelevant header/footer lines
                if "Page" in line or "Account Number" in line or "Opening Balance" in line:
                    continue

                # Try to match a transaction line
                match = date_pattern.match(line)
                if match and current_section:
                    date, desc, amount_str = match.groups()
                    
                    # Clean up description (remove extra spaces)
                    desc = desc.strip()
                    
                    # Parse amount
                    amount = parse_amount(amount_str)
                    
                    # For withdrawals, ensure amount is negative if logic dictates, 
                    # though statements usually list positive numbers in withdrawal sections.
                    # We'll keep raw magnitude but add a "Type" column.
                    
                    transactions.append({
                        "Date": date,
                        "Description": desc,
                        "Amount": amount,
                        "Type": current_section,
                        "Raw_Line": line 
                    })
                
                # HANDLE MULTI-LINE DESCRIPTIONS (Advanced Logic)
                # If a line doesn't start with a date but we just added a transaction,
                # it's likely a continuation of the previous description.
                elif transactions and not re.match(r'\d{2}/\d{2}', line):
                    # Check if it looks like a balance summary line or junk
                    if "$" in line and "Balance" in line:
                        continue
                        
                    # Append to previous transaction description
                    # Heuristic: Only append if the line is somewhat short or indented
                    # (This is where "MinerU" or complex logic helps, but simple appending works for 90% of cases)
                    last_txn = transactions[-1]
                    # Avoid merging unrelated numbers
                    if not re.search(r'\d+\.\d{2}$', line): 
                        last_txn["Description"] += " " + line

    return pd.DataFrame(transactions)

# --- UI ---
uploaded_file = st.file_uploader("Upload Chase PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Extracting data purely with algorithms..."):
        try:
            df = extract_chase_transactions(uploaded_file)
            
            if not df.empty:
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # Show Summary
                col1, col2, col3 = st.columns(3)
                total_deposits = df[df['Type'] == 'Deposit']['Amount'].sum()
                total_withdrawals = df[df['Type'] == 'Withdrawal']['Amount'].sum()
                
                col1.metric("Total Deposits", f"${total_deposits:,.2f}")
                col2.metric("Total Withdrawals", f"${total_withdrawals:,.2f}")
                col3.metric("Net Change", f"${(total_deposits - total_withdrawals):,.2f}")
                
                # Data Grid
                st.dataframe(df, use_container_width=True)
                
                # CSV Download
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "Download as CSV",
                    csv,
                    "bank_statement_data.csv",
                    "text/csv",
                    key='download-csv'
                )
            else:
                st.warning("No transactions found. Ensure this is a standard Chase PDF.")
                
        except Exception as e:
            st.error(f"Error parsing PDF: {str(e)}")

with st.expander("How this works (The 'No-AI' Logic)"):
    st.code("""
# The Logic Pattern (Regex)
# We look for:
# 1. A date at the start (08/01)
# 2. Any text in the middle (Description)
# 3. A monetary number at the end (1,260.68)

date_pattern = re.compile(r'^(\d{2}/\d{2})\s+(.*)\s+(-?\$?[\d,]+\.\d{2})$')
    """, language="python")

