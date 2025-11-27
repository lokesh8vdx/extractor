import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

st.set_page_config(page_title="No-AI Bank Extractor", layout="wide")

st.title("📄 Chase Statements Extractor (Rule-Based)")
st.markdown("""
This app extracts transactions from Chase bank statements without using AI. 
It handles standard sections to spatially analyze the text layout and Regex to parse dates and amounts.
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
    balances = []
    checking_summary = []
    
    with pdfplumber.open(pdf_file) as pdf:
        for i, page in enumerate(pdf.pages):
            page_num = i + 1
            # Extract text with layout preservation
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
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
            balance_pattern = re.compile(r'(\d{2}/\d{2})\s+(-?\$?[\d,]+\.\d{2})')

            # Pattern for Checking Summary
            # Matches: Label (text), Optional Count (int), Amount (currency)
            summary_pattern = re.compile(r'^(.*?)\s+(?:(\d+)\s+)?(-?\$?[\d,]+\.\d{2})$')

            current_section = None
            
            for line in lines:
                line = line.strip()
                
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
                        current_section = None # Transition handled by main loop next iter usually, but here we might be inside a block
                        # Actually, main loop logic checks headers first, so we don't need explicit break if we process headers before this block.
                        # But we are inside the loop iterating lines.
                        # Since we check headers at start of loop, we just need to ensure we don't process headers as summary items.
                        pass
                    continue

                # HANDLE DAILY ENDING BALANCE SECTION
                if current_section == "Daily Ending Balance":
                    # Find all date-amount pairs in the line
                    matches = balance_pattern.findall(line)
                    if matches:
                        for date, amount_str in matches:
                            # Fix date year if needed
                            if date.startswith('/'):
                                if balances:
                                    last_month = balances[-1]['Date'].split('/')[0]
                                    date = f"{last_month}{date}"
                                else:
                                    date = f"04{date}" # Fallback
                            
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
                    
                    # For withdrawals, ensure amount is negative if logic dictates, 
                    # though statements usually list positive numbers in withdrawal sections.
                    # We'll keep raw magnitude but add a "Type" column.
                    
                    transactions.append({
                        "Date": date,
                        "Description": desc,
                        "Amount": amount,
                        "Type": current_section,
                        "Page": page_num 
                    })
                
                # HANDLE MULTI-LINE DESCRIPTIONS (Advanced Logic)
                # If a line doesn't start with a date but we just added a transaction,
                # it's likely a continuation of the previous description.
                elif transactions and not re.match(r'\d{2}/\d{2}', line) and \
                     not (current_section == "Checks Paid" and re.match(r'^\d+', line)) and \
                     current_section not in ["Daily Ending Balance", "Checking Summary"]:
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

    return pd.DataFrame(transactions), pd.DataFrame(balances), pd.DataFrame(checking_summary)

# --- UI ---
uploaded_file = st.file_uploader("Upload Chase PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Extracting data purely with algorithms..."):
        try:
            df, balance_df, summary_df = extract_chase_transactions(uploaded_file)
            
            if not df.empty:
                st.success(f"Successfully extracted {len(df)} transactions!")
                
                # Show Summary
                if not summary_df.empty:
                    st.subheader("Checking Summary")
                    st.dataframe(summary_df, use_container_width=True)
                
                col1, col2, col3 = st.columns(3)
                total_deposits = df[df['Type'] == 'Deposit']['Amount'].sum()
                
                # Calculate Withdrawal subtotals
                total_atm = df[df['Type'] == 'ATM & Debit Withdrawal']['Amount'].sum()
                total_electronic = df[df['Type'] == 'Electronic Withdrawal']['Amount'].sum()
                total_checks = df[df['Type'] == 'Checks Paid']['Amount'].sum()
                total_other = df[df['Type'] == 'Other Withdrawal']['Amount'].sum()
                total_withdrawals = total_atm + total_electronic + total_checks + total_other
                
                total_fees = df[df['Type'] == 'Fee']['Amount'].sum()
                
                col1.metric("Total Deposits", f"${total_deposits:,.2f}")
                
                # Custom HTML/Metric for Withdrawals with breakdown
                col2.metric(
                    "Total Withdrawals", 
                    f"${total_withdrawals:,.2f}",
                    help=f"ATM: ${total_atm:,.2f} | Elec: ${total_electronic:,.2f} | Checks: ${total_checks:,.2f} | Other: ${total_other:,.2f}"
                )
                col2.caption(f"(ATM: ${total_atm:,.2f} + Elec: ${total_electronic:,.2f} + Checks: ${total_checks:,.2f} + Other: ${total_other:,.2f})")
                
                col3.metric("Total Fees", f"${total_fees:,.2f}")
                
                st.subheader("Transactions")
                # Data Grid
                st.dataframe(df, use_container_width=True)
                
                # CSV Download
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "Download Transactions CSV",
                    csv,
                    "bank_statement_transactions.csv",
                    "text/csv",
                    key='download-csv'
                )
                
                if not balance_df.empty:
                    st.divider()
                    st.subheader("Daily Ending Balances")
                    st.dataframe(balance_df, use_container_width=True)
                    
                    csv_bal = balance_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "Download Balances CSV",
                        csv_bal,
                        "bank_statement_balances.csv",
                        "text/csv",
                        key='download-bal-csv'
                    )

            else:
                st.warning("No transactions found. Ensure this is a standard Chase PDF.")
                
        except Exception as e:
            st.error(f"Error parsing PDF: {str(e)}")

with st.expander("How this works (The 'No-AI' Logic)"):
    st.code("""
# The Logic Pattern (Regex)
# We look for:
# 1. A date at the start (08/01) or hidden in prefix text
# 2. Any text in the middle (Description)
# 3. A monetary number at the end (1,260.68)
# 4. Optional trailing noise (e.g. Page number)

date_pattern = re.compile(r'(?:.*?)\s*(\d{0,2}/\d{2})\s+(.*)\s+(-?\$?[\d,]+\.\d{2})(?:\s.*)?$')
    """, language="python")
