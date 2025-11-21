import streamlit as st
import pdfplumber
import pandas as pd
import re
import plotly.express as px

# --- 1. CONFIGURATION & SETUP ---
st.set_page_config(page_title="Bank Statement Analyzer", layout="wide")

st.title("📊 Bank Statement Analyzer")
st.markdown("""
This app extracts transactions from **Bank of Belleville** PDF statements.
It parses Credit/Debit sections, visualizes spending, and exports data to CSV.
""")

# --- 2. EXTRACTION LOGIC ---
def extract_data_from_pdf(uploaded_file):
    """
    Parses the specific format of the uploaded bank statement.
    """
    data = []
    date_pattern = re.compile(r'^(\d{2}/\d{2}/\d{2})')
    current_section = None
    
    # pdfplumber can read from the uploaded file object directly
    with pdfplumber.open(uploaded_file) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
                
            lines = text.split('\n')
            
            for line in lines:
                clean_line = line.strip()
                
                # Section Detection
                if "ALL CREDIT ACTIVITY" in clean_line:
                    current_section = "CREDIT"
                    continue
                elif "ELECTRONIC DEBITS" in clean_line:
                    current_section = "DEBIT"
                    continue
                elif "DAILY BALANCE SUMMARY" in clean_line:
                    current_section = "IGNORE"
                    continue
                elif "CHECKS AND OTHER DEBITS" in clean_line:
                    current_section = "DEBIT"
                    continue
                
                # Skip invalid sections
                if current_section == "IGNORE" or current_section is None:
                    continue
                
                # Parse Transaction Lines
                match = date_pattern.match(clean_line)
                if match:
                    date_str = match.group(1)
                    remainder = clean_line[len(date_str):].strip()
                    
                    # Extract Amount (last element) and Description
                    parts = remainder.split()
                    if len(parts) > 0:
                        raw_amount = parts[-1]
                        description = " ".join(parts[:-1])
                        
                        try:
                            # Clean currency string
                            amount = float(raw_amount.replace(',', ''))
                            
                            # Apply negative sign for Debits
                            if current_section == "DEBIT":
                                amount = -abs(amount)
                            
                            data.append({
                                "Date": date_str,
                                "Description": description,
                                "Amount": amount,
                                "Type": current_section
                            })
                        except ValueError:
                            continue

    return pd.DataFrame(data)

# --- 3. MAIN APPLICATION UI ---

uploaded_file = st.file_uploader("Upload Bank Statement (PDF)", type="pdf")

if uploaded_file is not None:
    with st.spinner('Extracting data...'):
        df = extract_data_from_pdf(uploaded_file)
    
    if not df.empty:
        # --- PRE-PROCESSING ---
        # Convert Date to datetime objects for sorting/graphing
        df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%y')
        df = df.sort_values(by='Date')
        
        # Basic Metrics
        total_income = df[df['Amount'] > 0]['Amount'].sum()
        total_expense = df[df['Amount'] < 0]['Amount'].sum()
        net_flow = total_income + total_expense

        # --- METRICS ROW ---
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Deposits", f"${total_income:,.2f}")
        col2.metric("Total Withdrawals", f"${total_expense:,.2f}")
        col3.metric("Net Flow", f"${net_flow:,.2f}", delta_color="normal")
        
        st.divider()

        # --- VISUALIZATION ROW ---
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.subheader("Daily Transaction Volume")
            # Resample by day to show daily activity
            daily_df = df.groupby('Date')['Amount'].sum().reset_index()
            fig_bar = px.bar(daily_df, x='Date', y='Amount', 
                             color='Amount',
                             color_continuous_scale=px.colors.diverging.Tealrose,
                             title="Daily Net Spending vs Income")
            st.plotly_chart(fig_bar, use_container_width=True)
            
        with col_chart2:
            st.subheader("Cumulative Balance Impact")
            # Calculate running total (assuming starting balance is 0 relative to statement)
            df['Running_Total'] = df['Amount'].cumsum()
            fig_line = px.line(df, x='Date', y='Running_Total', 
                               title="Cumulative Cash Flow Trend",
                               markers=True)
            st.plotly_chart(fig_line, use_container_width=True)

        # --- DATA TABLE & DOWNLOAD ---
        st.subheader("Transaction Details")
        st.dataframe(df, use_container_width=True)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name="extracted_transactions.csv",
            mime="text/csv",
        )
        
    else:
        st.error("No transactions found. Please check if the PDF format matches the expected Bank of Belleville layout.")

else:
    st.info("Please upload a PDF file to begin.")

# --- 4. SIDEBAR (Optional Context) ---
with st.sidebar:
    st.header("About")
    st.write("""
    **Logic:** 1. Scans for `ALL CREDIT ACTIVITY` (Deposits)
    2. Scans for `ELECTRONIC DEBITS` (Withdrawals)
    3. Extracts Dates, Descriptions, and Amounts.
    
    **Tech Stack:**
    - `pdfplumber` for OCR/Parsing
    - `pandas` for Data Manipulation
    - `plotly` for Interactive Charts
    """)