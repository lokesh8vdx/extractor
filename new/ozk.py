import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

def extract_wells_fargo_transactions(pdf_file):
    """
    Parses Wells Fargo Business Checking PDF statements.
    """
    transactions = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split('\n')
            
            # Regex to find lines starting with a date (e.g., 4/1 or 04/01)
            # Wells Fargo Business format usually starts lines with the date.
            date_pattern = re.compile(r'^(\d{1,2}/\d{1,2})\s+')
            
            # Money pattern to identify amounts at the end of lines
            money_pattern = re.compile(r'([\d,]+\.\d{2})')

            current_transaction = None

            for line in lines:
                # Skip page headers/footers and summary tables
                if "Page" in line and "of" in line:
                    continue
                if "Beginning balance" in line or "Ending balance" in line:
                    continue
                if "Transaction history" in line.lower():
                    continue

                # Check if line starts with a date (New Transaction)
                match = date_pattern.match(line)
                
                if match:
                    # If we were building a transaction, save it before starting new one
                    if current_transaction:
                        transactions.append(current_transaction)
                    
                    date = match.group(1)
                    remaining_text = line[len(date):].strip()
                    
                    # Logic to split description and amounts
                    # We split by 2+ spaces to find distinct columns
                    parts = re.split(r'\s{2,}', remaining_text)
                    
                    description = parts[0]
                    amount_credit = 0.0
                    amount_debit = 0.0
                    balance = 0.0
                    
                    # Analyze numeric parts to assign Credits vs Debits
                    # This logic depends on the column order: Description | Credit | Debit | Balance
                    # We look at the amounts found at the end of the line
                    amounts = money_pattern.findall(line)
                    
                    # Simple heuristic: Check visual layout or count of numbers
                    # If 3 numbers: Credit/Debit, Debit/Credit, Balance
                    # If 2 numbers: Amount, Balance
                    # If 1 number: Amount (Balance might be empty)
                    
                    # To make this robust for this specific file, we rely on the parts list
                    # Usually: [Description, Amount, Balance] or [Description, Amount]
                    
                    # Cleaning amounts
                    clean_nums = []
                    for p in parts[1:]:
                        # Remove non-numeric chars except dot and comma
                        clean = p.replace('$', '').replace(',', '')
                        if re.match(r'^-?\d+\.\d{2}$', clean):
                            clean_nums.append(float(clean))
                    
                    # Wells Fargo Logic: 
                    # If the description indicates a deposit (Zelle, Transfer From, Deposit), it's a credit.
                    # Otherwise it is likely a debit. 
                    # Ideally, we use x-coordinates from pdfplumber, but text parsing is faster for a demo.
                    
                    # Let's attempt to categorize based on parsed numbers
                    if len(clean_nums) > 0:
                        # If the last number looks like a running balance (usually matches the ending balance pattern), keep it separate
                        # For now, we will store the raw extracted amount and refine via description logic
                        raw_amount = clean_nums[0]
                        
                        # Heuristic: Deposits often have keywords
                        is_deposit = any(keyword in description.lower() for keyword in ['deposit', 'transfer from', 'zelle from', 'credit', 'refund'])
                        
                        if is_deposit:
                            amount_credit = raw_amount
                        else:
                            amount_debit = raw_amount
                            
                        if len(clean_nums) > 1:
                            balance = clean_nums[-1]
                    
                    current_transaction = {
                        "Date": date,
                        "Description": description,
                        "Credits": amount_credit if amount_credit > 0 else None,
                        "Debits": amount_debit if amount_debit > 0 else None,
                        "Balance": balance if balance > 0 else None
                    }

                # If line doesn't start with date but we have a current transaction, append to description
                elif current_transaction and not date_pattern.match(line):
                    # Check if this is just a noise line or part of description
                    if not re.search(r'\d{1,2}/\d{1,2}/\d{4}', line): # Avoid appending footer dates
                        current_transaction["Description"] += " " + line.strip()
            
            # Append the last transaction of the page
            if current_transaction:
                transactions.append(current_transaction)

    return pd.DataFrame(transactions)

# --- STREAMLIT UI ---
st.set_page_config(page_title="Bank Statement Parser", layout="wide")

st.title("🏦 Wells Fargo Statement Analyzer")
st.markdown("""
This tool extracts transaction data from **Wells Fargo Business Checking** PDF statements.
It handles multi-line descriptions and separates credits from debits.
""")

uploaded_file = st.file_uploader("Upload your April Statement (PDF)", type="pdf")

if uploaded_file:
    with st.spinner("Analyzing document structure..."):
        try:
            df = extract_wells_fargo_transactions(uploaded_file)
            
            # Data Cleaning
            df['Date'] = df['Date'] + "/2025" # Appending year based on context
            df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y', errors='coerce')
            
            # Display Metrics
            col1, col2, col3 = st.columns(3)
            total_credits = df['Credits'].sum()
            total_debits = df['Debits'].sum()
            
            col1.metric("Total Deposits/Credits", f"${total_credits:,.2f}")
            col2.metric("Total Withdrawals/Debits", f"${total_debits:,.2f}")
            col3.metric("Net Change", f"${(total_credits - total_debits):,.2f}")
            
            st.divider()
            
            # Display Dataframe
            st.subheader("Extracted Transactions")
            st.dataframe(
                df, 
                column_config={
                    "Date": st.column_config.DateColumn("Date", format="MM/DD/YYYY"),
                    "Credits": st.column_config.NumberColumn("Deposits ($)", format="$%.2f"),
                    "Debits": st.column_config.NumberColumn("Withdrawals ($)", format="$%.2f"),
                    "Balance": st.column_config.NumberColumn("Daily Balance ($)", format="$%.2f"),
                },
                use_container_width=True,
                height=600
            )
            
            # Download Button
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name="extracted_bank_statement.csv",
                mime="text/csv",
            )
            
        except Exception as e:
            st.error(f"Error parsing file: {e}")
            st.info("Ensure this is a standard text-based PDF (not a scanned image) from Wells Fargo.")