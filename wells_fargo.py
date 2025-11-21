import streamlit as st
import pdfplumber
import pandas as pd
import re
import altair as alt

st.set_page_config(page_title="Universal Bank Parser", layout="wide")

# --- UTILS ---
def parse_amount(amount_str):
    """Cleans and converts amount string to float."""
    if not amount_str: return 0.0
    # Remove currency symbols, commas, and whitespace
    clean_str = str(amount_str).replace('$', '').replace(',', '').replace(' ', '')
    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def identify_bank(text):
    """Scans text for bank fingerprints."""
    text_lower = text.lower()
    if "chase" in text_lower and "jpmorgan" in text_lower:
        return "Chase"
    if "wells fargo" in text_lower:
        return "Wells Fargo"
    if "bank of america" in text_lower:
        return "Bank of America"
    return "Unknown"

def extract_year_from_header(text):
    """Tries to find a 4-digit year in the first page text."""
    match = re.search(r'(20\d{2})', text)
    return match.group(1) if match else "2025"

# --- STRATEGY 1: CHASE (REGEX / SECTIONS) ---
def parse_chase(pdf, current_year):
    transactions = []
    
    # Chase-specific patterns
    date_pattern = re.compile(r'^(\d{2}/\d{2})\s+(.*)\s+(-?\$?[\d,]+\.\d{2})$')
    SECTION_KEYWORDS = ["DEPOSIT", "ADDITION", "WITHDRAWAL", "DEBIT", "FEE", "PAYMENT"]
    
    for page in pdf.pages:
        text = page.extract_text(x_tolerance=2, y_tolerance=2)
        if not text: continue
        
        lines = text.split('\n')
        current_section = "Uncategorized"
        
        for line in lines:
            line = line.strip()
            upper_line = line.upper()
            
            # Detect Section
            if (any(k in upper_line for k in SECTION_KEYWORDS) and "TOTAL" not in upper_line and len(line) < 80):
                current_section = line.title()
                continue
                
            # Parse Line
            match = date_pattern.match(line)
            if match:
                date_part, desc, amount_str = match.groups()
                amount = parse_amount(amount_str)
                
                # Logic: Section-based signing
                sec_lower = current_section.lower()
                if any(x in sec_lower for x in ['withdrawal', 'debit', 'fee', 'payment']):
                    amount = -abs(amount)
                elif any(x in sec_lower for x in ['deposit', 'add']):
                    amount = abs(amount)
                
                transactions.append({
                    "Date": f"{date_part}/{current_year}",
                    "Description": desc.strip(),
                    "Amount": amount,
                    "Bank": "Chase"
                })
    return transactions

# --- STRATEGY 2: WELLS FARGO (TABLE GRID) ---
def parse_wells_fargo(pdf, current_year):
    transactions = []
    
    for page in pdf.pages:
        # Wells Fargo uses tables. extract_table() is smarter than Regex for this.
        # It returns a list of lists: [['3/3', 'Check#', 'Desc', 'Dep', 'With', 'Bal']]
        tables = page.extract_tables()
        
        for table in tables:
            for row in table:
                # Sanity check: Row must have at least 4 columns and start with a date-like string
                if not row or len(row) < 4: continue
                
                # Check if first column looks like a date (M/D or MM/DD)
                first_col = str(row[0]).strip()
                if not re.match(r'\d{1,2}/\d{1,2}', first_col):
                    continue
                    
                # Wells Fargo Column Mapping (based on standard PDF layout)
                # Col 0: Date
                # Col 2: Description
                # Col 3: Deposits/Credits
                # Col 4: Withdrawals/Debits
                
                date_part = first_col
                desc = str(row[2]).replace('\n', ' ').strip() if len(row) > 2 else ""
                
                # Try parsing Deposit (Col 3)
                deposit_str = row[3] if len(row) > 3 else None
                deposit = parse_amount(deposit_str)
                
                # Try parsing Withdrawal (Col 4)
                withdrawal_str = row[4] if len(row) > 4 else None
                withdrawal = parse_amount(withdrawal_str)
                
                # Logic: If deposit exists, add positive txn. If withdrawal, add negative.
                # (Sometimes a single line might have both if it's a summary, but rarely)
                
                if deposit > 0:
                    transactions.append({
                        "Date": f"{date_part}/{current_year}",
                        "Description": desc,
                        "Amount": deposit,
                        "Bank": "Wells Fargo"
                    })
                
                if withdrawal > 0:
                    transactions.append({
                        "Date": f"{date_part}/{current_year}",
                        "Description": desc,
                        "Amount": -withdrawal, # Flip sign for withdrawal
                        "Bank": "Wells Fargo"
                    })

    return transactions

# --- MAIN ROUTER ---
def process_pdf(pdf_file):
    with pdfplumber.open(pdf_file) as pdf:
        # 1. Identify Bank & Year from Page 1
        first_page_text = pdf.pages[0].extract_text()
        bank_name = identify_bank(first_page_text)
        year = extract_year_from_header(first_page_text)
        
        st.write(f"**Detected:** {bank_name} ({year})")
        
        # 2. Route to Strategy
        if bank_name == "Chase":
            return parse_chase(pdf, year)
        elif bank_name == "Wells Fargo":
            return parse_wells_fargo(pdf, year)
        else:
            st.error("Bank format not recognized (Supports: Chase, Wells Fargo)")
            return []

# --- UI ---
st.title("🤖 Universal Bank Statement Parser")
st.markdown("Automatically detects format (Chase/Wells Fargo) and extracts data using the best strategy.")

uploaded_files = st.file_uploader("Upload PDF Statements", type=['pdf'], accept_multiple_files=True)

if uploaded_files:
    all_txns = []
    
    for file in uploaded_files:
        with st.expander(f"Processing {file.name}", expanded=True):
            txns = process_pdf(file)
            if txns:
                all_txns.extend(txns)
                st.success(f"Extracted {len(txns)} transactions")
    
    if all_txns:
        df = pd.DataFrame(all_txns)
        
        # Data Cleaning
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df.sort_values('Date', inplace=True)
        
        # Dashboard
        st.divider()
        st.header("Analysis")
        
        col1, col2, col3 = st.columns(3)
        total_rev = df[df['Amount'] > 0]['Amount'].sum()
        total_exp = df[df['Amount'] < 0]['Amount'].sum()
        
        col1.metric("Total Deposits", f"${total_rev:,.2f}")
        col2.metric("Total Withdrawals", f"${abs(total_exp):,.2f}")
        col3.metric("Net Cash Flow", f"${(total_rev + total_exp):,.2f}")
        
        # Chart
        st.subheader("Cash Flow Timeline")
        chart = alt.Chart(df).mark_bar().encode(
            x='Date',
            y='Amount',
            color=alt.condition(
                alt.datum.Amount > 0,
                alt.value('#2ecc71'),  # Green for positive
                alt.value('#e74a3b')   # Red for negative
            ),
            tooltip=['Date', 'Description', 'Amount']
        )
        st.altair_chart(chart, use_container_width=True)
        
        # Raw Data
        st.subheader("Transaction Ledger")
        st.dataframe(df, use_container_width=True)