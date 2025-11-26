import streamlit as st
import pdfplumber
import pandas as pd
import re
import io

# --- Page Config ---
st.set_page_config(page_title="Bank Statement Extractor", layout="wide")

# --- Helper Functions ---

def parse_amount(amount_str):
    """
    Cleans amount strings. 
    Handles: '1,234.56', '1,234.56+', '1,234.56-', '(1,234.56)'
    """
    if not amount_str:
        return 0.0
    
    # Remove commas and spaces
    clean_str = amount_str.replace(',', '').replace(' ', '').strip()
    
    # Handle negative signs at end or parentheses
    is_negative = False
    if clean_str.endswith('-') or (clean_str.startswith('(') and clean_str.endswith(')')):
        is_negative = True
        clean_str = clean_str.replace('-', '').replace('(', '').replace(')', '')
    elif clean_str.endswith('+'):
        clean_str = clean_str.replace('+', '')
        
    try:
        val = float(clean_str)
        return -val if is_negative else val
    except ValueError:
        return 0.0

def extract_data_from_pdf(uploaded_file):
    """
    Extracts transactions from a PDF file using pdfplumber and regex.
    Logic tailored for Bank of Belleville format but generalized for Date-Desc-Amount lines.
    """
    transactions = []
    
    # Regex to identify the start of a transaction line.
    # Looks for MM/DD/YY at the start.
    # Captures: (Date) (Description content) (Amount at end)
    # The amount regex allows for trailing + or -
    line_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})\s+(.+?)\s+(-?[\d,]+\.\d{2}[+-]?)$')
    
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            lines = text.split('\n')
            
            for line in lines:
                line = line.strip()
                match = line_pattern.match(line)
                
                if match:
                    # Found a new transaction row
                    date, desc, amount = match.groups()
                    
                    transactions.append({
                        "Date": date,
                        "Description": desc.strip(),
                        "Amount": parse_amount(amount),
                        "Raw_Amount": amount # Keep strictly for debugging
                    })
                else:
                    # If line is not empty and we have previous transactions, 
                    # this might be a multi-line description (common in your PDF)
                    # Logic: If line is short or doesn't look like a header/footer, append it.
                    if transactions and line and not re.match(r'Page \d+', line) and "Balance" not in line:
                        # Heuristic: Don't append if it looks like a separate table header
                        if "Description" not in line and "Amount" not in line:
                            transactions[-1]["Description"] += " " + line.strip()

    return pd.DataFrame(transactions)

# --- Main App UI ---

st.title("📄 Bank Statement to CSV Converter")
st.markdown("""
This tool extracts transactions from PDF bank statements. 
It uses pattern recognition to find dates and amounts, merging multi-line descriptions automatically.
""")

# File Uploader
uploaded_file = st.file_uploader("Upload Bank Statement (PDF)", type="pdf")

if uploaded_file is not None:
    with st.spinner('Extracting data...'):
        try:
            # Extract
            df = extract_data_from_pdf(uploaded_file)
            
            if not df.empty:
                # Convert Date to datetime for sorting/graphing
                df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
                
                # Summary Metrics
                st.divider()
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Transactions", len(df))
                col2.metric("Total Credits (+)", f"${df[df['Amount'] > 0]['Amount'].sum():,.2f}")
                col3.metric("Total Debits (-)", f"${df[df['Amount'] < 0]['Amount'].sum():,.2f}")
                
                # Tabs for Data & Visuals
                tab1, tab2, tab3 = st.tabs(["📝 Data Editor", "📊 Visualizations", "🔍 Raw Extraction Logic"])
                
                with tab1:
                    st.subheader("Review and Edit Data")
                    st.caption("Double-click cells to edit descriptions or fix amounts before downloading.")
                    
                    # Editable Dataframe
                    edited_df = st.data_editor(
                        df, 
                        num_rows="dynamic",
                        column_config={
                            "Amount": st.column_config.NumberColumn(format="$%.2f"),
                            "Date": st.column_config.DateColumn(format="MM/DD/YYYY")
                        },
                        use_container_width=True
                    )
                    
                    # Download Button
                    csv = edited_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📥 Download CSV",
                        data=csv,
                        file_name="bank_statement_extracted.csv",
                        mime="text/csv",
                        type="primary"
                    )

                with tab2:
                    st.subheader("Daily Spending Trend")
                    # Aggregate by date
                    daily_sum = df.groupby('Date')['Amount'].sum().reset_index()
                    st.bar_chart(daily_sum, x='Date', y='Amount')

                with tab3:
                    st.subheader("Debugger")
                    st.text("Sample of raw lines from the first page for verification:")
                    with pdfplumber.open(uploaded_file) as pdf:
                        first_page = pdf.pages[0].extract_text()
                        st.code(first_page)
            
            else:
                st.error("Could not find any transactions matching the 'Date Description Amount' pattern.")
                st.info("Try checking if the PDF is an image scan (needs OCR) or has a very unusual layout.")
                
        except Exception as e:
            st.error(f"An error occurred during processing: {e}")

else:
    st.info("👆 Upload a PDF to get started.")

    # Sidebar tips
    with st.sidebar:
        st.header("How it works")
        st.write("""
        1. **Upload** your Bank of Belleville (or similar) PDF.
        2. **Auto-Detect**: The app looks for lines starting with dates (e.g., `03/10/25`).
        3. **Merge**: Lines following a transaction are treated as description continuations.
        4. **Edit**: Use the table to correct any mistakes.
        5. **Download**: Get a clean CSV for Excel or QuickBooks.
        """)