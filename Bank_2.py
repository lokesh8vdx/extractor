import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

st.set_page_config(page_title="No-AI Bank Extractor", layout="wide")

st.title("📄 Bank Statement Extractor (Auto-Detect Sections)")
st.markdown("""
This app extracts transactions from bank statements. 
It uses **heuristic patterns** to automatically detect section headers (like "Deposits", "Withdrawals", "Fees") 
instead of relying on hardcoded bank-specific names.
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

def extract_transactions_dynamic(pdf_file):
    transactions = []
    
    # Keywords that suggest a line is a section header
    # We look for these terms in uppercase lines to identify categories
    SECTION_KEYWORDS = [
        "DEPOSIT", "ADDITION", "CREDIT",     # Money In
        "WITHDRAWAL", "DEBIT", "PAYMENT",    # Money Out
        "FEE", "CHARGE", "CHECK", "DRAFT",   # Fees/Checks
        "ACTIVITY", "SUMMARY"                # General
    ]
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if not text: continue
            
            lines = text.split('\n')
            
            # Standard Date Pattern: MM/DD (at start of line)
            # Matches: "08/01  Description...  1,200.00"
            date_pattern = re.compile(r'^(\d{2}/\d{2})\s+(.*)\s+(-?\$?[\d,]+\.\d{2})$')
            
            current_section = "Uncategorized"
            
            for line in lines:
                line = line.strip()
                upper_line = line.upper()
                
                # --- AUTO-DETECT SECTIONS ---
                # Heuristic 1: Contains a banking keyword
                # Heuristic 2: Not a "Total" summary line (e.g. "Total Deposits")
                # Heuristic 3: Not a transaction line (doesn't start with date)
                # Heuristic 4: Reasonably short (headers aren't paragraphs)
                if (any(keyword in upper_line for keyword in SECTION_KEYWORDS) 
                    and not upper_line.startswith("TOTAL")
                    and not re.match(r'^\d{2}/\d{2}', line)
                    and len(line) < 80):
                    
                    # Clean up the header title (e.g., "DEPOSITS AND ADDITIONS" -> "Deposits And Additions")
                    current_section = line.title()
                    continue
                
                # Skip irrelevant pages/headers
                if "Page" in line or "Account Number" in line or "Opening Balance" in line:
                    continue

                # --- DETECT TRANSACTION ---
                match = date_pattern.match(line)
                if match:
                    date, desc, amount_str = match.groups()
                    amount = parse_amount(amount_str)
                    
                    # Smart Signing: Heuristic to determine sign based on section name
                    # If section implies money leaving, make negative.
                    sec_lower = current_section.lower()
                    if any(x in sec_lower for x in ['withdrawal', 'debit', 'fee', 'payment', 'charge']):
                        # Ensure it's negative
                        amount = -abs(amount)
                    elif any(x in sec_lower for x in ['deposit', 'credit', 'addition']):
                        # Ensure it's positive
                        amount = abs(amount)
                    
                    transactions.append({
                        "Date": date,
                        "Description": desc.strip(),
                        "Amount": amount,
                        "Section": current_section,
                        "Raw_Line": line 
                    })
                
                # --- HANDLE MULTI-LINE DESCRIPTIONS ---
                elif transactions and not re.match(r'\d{2}/\d{2}', line):
                    # If line doesn't look like a date, a header, or a balance summary
                    if "Balance" not in line and "$" not in line:
                        last_txn = transactions[-1]
                        # Append if it looks like text text
                        if not re.search(r'\d+\.\d{2}$', line): 
                            last_txn["Description"] += " " + line

    return pd.DataFrame(transactions)

# --- UI ---
uploaded_file = st.file_uploader("Upload Bank PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Analyzing document structure..."):
        try:
            df = extract_transactions_dynamic(uploaded_file)
            
            if not df.empty:
                st.success(f"Successfully extracted {len(df)} transactions across {df['Section'].nunique()} sections!")
                
                # Show Categories Found
                st.write("### Detected Sections")
                st.write(list(df['Section'].unique()))
                
                # Summary Stats
                col1, col2, col3 = st.columns(3)
                
                # Filter based on sign for summary
                total_in = df[df['Amount'] > 0]['Amount'].sum()
                total_out = df[df['Amount'] < 0]['Amount'].sum()
                
                col1.metric("Total In (Deposits)", f"${total_in:,.2f}")
                col2.metric("Total Out (Withdrawals)", f"${abs(total_out):,.2f}")
                col3.metric("Net Flow", f"${(total_in + total_out):,.2f}")
                
                # Data Grid with Section filter
                section_filter = st.multiselect("Filter by Section", options=df['Section'].unique(), default=df['Section'].unique())
                filtered_df = df[df['Section'].isin(section_filter)]
                
                st.dataframe(filtered_df, use_container_width=True)
                
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "Download Full CSV",
                    csv,
                    "extracted_transactions.csv",
                    "text/csv"
                )
            else:
                st.warning("No transactions found. Try a different PDF or check if it's an image scan.")
                
        except Exception as e:
            st.error(f"Error: {str(e)}")

with st.expander("Logic Explanation"):
    st.markdown("""
    ### Auto-Detection Heuristics
    Instead of looking for exact names like "DEPOSITS AND ADDITIONS", the code now checks lines for:
    1.  **Keywords:** `DEPOSIT`, `WITHDRAWAL`, `FEE`, `CHECK`, `PAYMENT`, etc.
    2.  **Format:** Start of line, no date pattern, not a "Total" line.
    
    It uses the detected section title to categorize transactions and intelligently guess if the amount should be positive or negative.
    """)