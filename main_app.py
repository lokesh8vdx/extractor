import streamlit as st
import pdfplumber
import re
import pandas as pd
import io
from datetime import datetime

# Import bank parsers
from parsers.us_bank_parser import parse_us_bank_statement
from parsers.citizens_bank_parser import parse_citizens_bank_statement
from parsers.boa_parser import parse_boa_statement
from parsers.chase_parser import parse_chase_statement

st.set_page_config(page_title="Bank Statement Extractor", layout="wide")

st.title("🏦 Bank Statement Extractor")
st.markdown("""
This app automatically identifies the bank from your PDF statement and extracts transactions.
Currently supports: **U.S. Bank**, **Citizens Bank**, **Bank of America**, **Chase**
""")

def identify_bank(pdf_file):
    """
    Identifies the bank from the PDF content.
    Returns the bank name as a string.
    """
    try:
        # Reset file pointer if it's a BytesIO object
        if hasattr(pdf_file, 'seek'):
            pdf_file.seek(0)
        
        with pdfplumber.open(pdf_file) as pdf:
            if not pdf.pages:
                return "Unknown"
            
            # Extract text from first few pages to identify the bank
            text = ""
            for i, page in enumerate(pdf.pages[:3]):  # Check first 3 pages
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            
            text_lower = text.lower()
            
            # Chase identification patterns
            if "chase" in text_lower and ("jpmorgan" in text_lower or "chase bank" in text_lower):
                return "Chase"
            if "chase.com" in text_lower:
                return "Chase"
            
            # US Bank identification patterns
            if "u.s. bank" in text_lower or "us bank" in text_lower:
                # Additional check for US Bank specific patterns
                if "business statement" in text_lower or "member fdic" in text_lower:
                    return "US Bank"
                # Check for US Bank specific sections
                if "customer deposits" in text_lower or "card deposits" in text_lower:
                    return "US Bank"
                return "US Bank"
            
            # Bank of America identification patterns
            if "bank of america" in text_lower or "bofa" in text_lower:
                # Additional check for Bank of America specific patterns
                if "your checking account" in text_lower or "ending balance on" in text_lower:
                    return "Bank of America"
                # Check for Bank of America specific sections
                if "deposits and other credits" in text_lower or "withdrawals and other debits" in text_lower:
                    return "Bank of America"
                if "daily ledger balances" in text_lower:
                    return "Bank of America"
                return "Bank of America"
            
            # Citizens Bank identification patterns
            if ("citizens bank" in text_lower and "first citizens bank" not in text_lower) or "citizensbank.com" in text_lower:
                # Additional check for Citizens Bank specific patterns
                if "clearly better business checking" in text_lower or "commercial account" in text_lower:
                    return "Citizens Bank"
                # Check for Citizens Bank specific sections
                if "deposits&credits" in text_lower or "deposits&credit" in text_lower:
                    return "Citizens Bank"
                if "previousbalance" in text_lower or "currentbalance" in text_lower:
                    return "Citizens Bank"
                return "Citizens Bank"
            
            return "Unknown"
            
    except Exception as e:
        st.error(f"Error identifying bank: {str(e)}")
        return "Unknown"

# Main processing function
def process_pdf(pdf_file):
    """
    Main function that identifies the bank and routes to the appropriate parser.
    """
    # Reset file pointer
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)
    
    # Identify bank
    bank_name = identify_bank(pdf_file)
    
    # Reset file pointer again for parsing
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)
    
    # Route to appropriate parser
    if bank_name == "US Bank":
        return parse_us_bank_statement(pdf_file), bank_name
    elif bank_name == "Citizens Bank":
        return parse_citizens_bank_statement(pdf_file), bank_name
    elif bank_name == "Bank of America":
        return parse_boa_statement(pdf_file), bank_name
    elif bank_name == "Chase":
        return parse_chase_statement(pdf_file), bank_name
    else:
        st.error(f"Bank '{bank_name}' is not yet supported. Currently supports: U.S. Bank, Citizens Bank, Bank of America, Chase")
        return None, bank_name

# --- UI ---
uploaded_file = st.file_uploader("Upload Bank PDF Statement", type=['pdf'])

if uploaded_file:
    with st.spinner("Identifying bank and extracting data..."):
        try:
            pdf_file = io.BytesIO(uploaded_file.read())
            result = process_pdf(pdf_file)
            
            if result[0] is not None:
                df, extracted_summary, balance_df = result[0]
                bank_name = result[1]
                
                st.success(f"✅ Identified as: **{bank_name}**")
                
                if not df.empty:
                    # Filter out 'Unknown' types
                    df = df[~df['Type'].isin(['Unknown'])]
                    
                    st.success(f"Successfully extracted {len(df)} transactions!")
                    
                    # --- Standardize Signs for Calculation ---
                    # Create SignedAmount for daily ledger logic
                    def standardize_sign(row):
                        amount = row['Amount']
                        txn_type = row['Type']
                        
                        if bank_name == "Chase":
                            # Chase parser returns all positive
                            if txn_type in ['ATM & Debit Withdrawal', 'Electronic Withdrawal', 'Other Withdrawal', 'Checks Paid', 'Fee']:
                                return -abs(amount)
                            return abs(amount)
                            
                        elif bank_name == "Bank of America":
                            # BoA parser often returns positive for withdrawals/checks
                            if txn_type in ['Withdrawals', 'Checks', 'Service Fees']:
                                return -abs(amount)
                            return abs(amount)
                            
                        return amount

                    df['SignedAmount'] = df.apply(standardize_sign, axis=1)

                    # --- Computations for Validation (Bank-specific) ---
                    if bank_name == "US Bank":
                        computed_customer_deposits = df[df['Type'] == 'Customer Deposits']['Amount'].sum()
                        computed_other_deposits = df[df['Type'] == 'Other Deposits']['Amount'].sum()
                        computed_card_deposits = df[df['Type'] == 'Card Deposits']['Amount'].sum()
                        computed_card_withdrawals = abs(df[df['Type'] == 'Card Withdrawals']['Amount'].sum())
                        computed_other_withdrawals = abs(df[df['Type'] == 'Other Withdrawals']['Amount'].sum())
                        computed_checks = abs(df[df['Type'] == 'Checks Paid']['Amount'].sum())
                        
                        beg_bal = extracted_summary.get("Beginning Balance", 0.0)
                        computed_ending = beg_bal + computed_customer_deposits + computed_other_deposits + computed_card_deposits - computed_card_withdrawals - computed_other_withdrawals - computed_checks
                        
                        summary_data = [
                            {"Category": "Beginning Balance", "Extracted": extracted_summary.get("Beginning Balance", 0.0), 
                             "Computed": beg_bal, "Difference": 0.0},
                            {"Category": "Customer Deposits", "Extracted": extracted_summary.get("Customer Deposits", 0.0), 
                             "Computed": computed_customer_deposits, "Difference": extracted_summary.get("Customer Deposits", 0.0) - computed_customer_deposits},
                            {"Category": "Other Deposits", "Extracted": extracted_summary.get("Other Deposits", 0.0), 
                             "Computed": computed_other_deposits, "Difference": extracted_summary.get("Other Deposits", 0.0) - computed_other_deposits},
                            {"Category": "Card Deposits", "Extracted": extracted_summary.get("Card Deposits", 0.0), 
                             "Computed": computed_card_deposits, "Difference": extracted_summary.get("Card Deposits", 0.0) - computed_card_deposits},
                            {"Category": "Card Withdrawals", "Extracted": abs(extracted_summary.get("Card Withdrawals", 0.0)), 
                             "Computed": computed_card_withdrawals, "Difference": abs(extracted_summary.get("Card Withdrawals", 0.0)) - computed_card_withdrawals},
                            {"Category": "Other Withdrawals", "Extracted": abs(extracted_summary.get("Other Withdrawals", 0.0)), 
                             "Computed": computed_other_withdrawals, "Difference": abs(extracted_summary.get("Other Withdrawals", 0.0)) - computed_other_withdrawals},
                            {"Category": "Checks Paid", "Extracted": abs(extracted_summary.get("Checks Paid", 0.0)), 
                             "Computed": computed_checks, "Difference": abs(extracted_summary.get("Checks Paid", 0.0)) - computed_checks},
                            {"Category": "Ending Balance", "Extracted": extracted_summary.get("Ending Balance", 0.0), 
                             "Computed": computed_ending, "Difference": extracted_summary.get("Ending Balance", 0.0) - computed_ending},
                        ]
                    elif bank_name == "Citizens Bank":
                        computed_checks = df[df['Type'] == 'Checks']['Amount'].sum()
                        computed_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                        computed_debits = df[df['Type'] == 'Debits']['Amount'].sum()
                        
                        prev_bal = extracted_summary.get("Previous Balance", 0.0)
                        computed_ending = prev_bal + computed_checks + computed_debits + computed_deposits
                        
                        summary_data = [
                            {"Category": "Previous Balance", "Extracted": extracted_summary.get("Previous Balance", 0.0), 
                             "Computed": prev_bal, "Difference": 0.0},
                            {"Category": "Checks", "Extracted": -extracted_summary.get("Checks", 0.0), 
                             "Computed": computed_checks, "Difference": -extracted_summary.get("Checks", 0.0) - computed_checks},
                            {"Category": "Debits", "Extracted": -extracted_summary.get("Debits", 0.0), 
                             "Computed": computed_debits, "Difference": -extracted_summary.get("Debits", 0.0) - computed_debits},
                            {"Category": "Deposits/Credits", "Extracted": extracted_summary.get("Deposits/Credits", 0.0), 
                             "Computed": computed_deposits, "Difference": extracted_summary.get("Deposits/Credits", 0.0) - computed_deposits},
                            {"Category": "Current Balance", "Extracted": extracted_summary.get("Current Balance", 0.0), 
                             "Computed": computed_ending, "Difference": extracted_summary.get("Current Balance", 0.0) - computed_ending},
                        ]
                        beg_bal = prev_bal  # For balance computation below
                    elif bank_name == "Bank of America":
                        computed_deposits = df[df['Type'] == 'Deposits']['Amount'].sum()
                        computed_withdrawals = df[df['Type'] == 'Withdrawals']['Amount'].sum()
                        computed_checks = df[df['Type'] == 'Checks']['Amount'].sum()
                        computed_fees = df[df['Type'] == 'Service Fees']['Amount'].sum()
                        
                        beg_bal = extracted_summary.get("Beginning Balance", 0.0)
                        computed_ending = beg_bal + computed_deposits + computed_withdrawals + computed_checks + computed_fees
                        
                        summary_data = [
                            {"Category": "Beginning Balance", "Extracted": extracted_summary.get("Beginning Balance", 0.0), 
                             "Computed": beg_bal, "Difference": 0.0},
                            {"Category": "Deposits/Credits", "Extracted": extracted_summary.get("Deposits/Credits", 0.0), 
                             "Computed": computed_deposits, "Difference": extracted_summary.get("Deposits/Credits", 0.0) - computed_deposits},
                            {"Category": "Withdrawals/Debits", "Extracted": extracted_summary.get("Withdrawals/Debits", 0.0), 
                             "Computed": computed_withdrawals, "Difference": extracted_summary.get("Withdrawals/Debits", 0.0) - computed_withdrawals},
                            {"Category": "Checks", "Extracted": extracted_summary.get("Checks", 0.0), 
                             "Computed": computed_checks, "Difference": extracted_summary.get("Checks", 0.0) - computed_checks},
                            {"Category": "Service Fees", "Extracted": extracted_summary.get("Service Fees", 0.0), 
                             "Computed": computed_fees, "Difference": extracted_summary.get("Service Fees", 0.0) - computed_fees},
                            {"Category": "Ending Balance", "Extracted": extracted_summary.get("Ending Balance", 0.0), 
                             "Computed": computed_ending, "Difference": extracted_summary.get("Ending Balance", 0.0) - computed_ending},
                        ]
                    elif bank_name == "Chase":
                        computed_deposits = df[df['Type'] == 'Deposit']['Amount'].sum()
                        
                        # Withdrawals, Checks, Fees might be positive or negative in DF depending on parser/PDF
                        # but they are outflows. We enforce subtraction.
                        computed_withdrawals = abs(df[df['Type'].isin(['ATM & Debit Withdrawal', 'Electronic Withdrawal', 'Other Withdrawal'])]['Amount'].sum())
                        computed_checks = abs(df[df['Type'] == 'Checks Paid']['Amount'].sum())
                        computed_fees = abs(df[df['Type'] == 'Fee']['Amount'].sum())
                        
                        beg_bal = extracted_summary.get("Beginning Balance", 0.0)
                        
                        computed_ending = beg_bal + computed_deposits - computed_withdrawals - computed_checks - computed_fees
                        
                        summary_data = [
                            {"Category": "Beginning Balance", "Extracted": extracted_summary.get("Beginning Balance", 0.0), 
                             "Computed": beg_bal, "Difference": 0.0},
                            {"Category": "Deposits", "Extracted": extracted_summary.get("Deposits", 0.0), 
                             "Computed": computed_deposits, "Difference": extracted_summary.get("Deposits", 0.0) - computed_deposits},
                            {"Category": "Withdrawals", "Extracted": extracted_summary.get("Withdrawals", 0.0), 
                             "Computed": computed_withdrawals, "Difference": extracted_summary.get("Withdrawals", 0.0) - computed_withdrawals},
                            {"Category": "Checks Paid", "Extracted": extracted_summary.get("Checks", 0.0), 
                             "Computed": computed_checks, "Difference": extracted_summary.get("Checks", 0.0) - computed_checks},
                            {"Category": "Fees", "Extracted": extracted_summary.get("Fees", 0.0), 
                             "Computed": computed_fees, "Difference": extracted_summary.get("Fees", 0.0) - computed_fees},
                            {"Category": "Ending Balance", "Extracted": extracted_summary.get("Ending Balance", 0.0), 
                             "Computed": computed_ending, "Difference": extracted_summary.get("Ending Balance", 0.0) - computed_ending},
                        ]
                    else:
                        summary_data = []
                        beg_bal = 0.0
                    
                    summary_df = pd.DataFrame(summary_data)
                    
                    # --- Balance Summary Differences ---
                    balance_summary_diffs = []
                    if not balance_df.empty:
                        df_with_dt = df.copy()
                        df_with_dt['DateTime'] = pd.to_datetime(df_with_dt['Date'], format='%m/%d/%y', errors='coerce')
                        
                        balance_df['DateTime'] = pd.to_datetime(balance_df['Date'], format='%m/%d/%y', errors='coerce')
                        balance_df = balance_df.sort_values('DateTime', ascending=True).reset_index(drop=True)
                        
                        # Use robust per-row calculation instead of optimization map
                        # This avoids issues if transaction dates don't perfectly align or if there are gaps
                        for idx, row in balance_df.iterrows():
                            date_dt = row['DateTime']
                            if pd.isna(date_dt):
                                continue
                                
                            transactions_up_to_date = df_with_dt[df_with_dt['DateTime'] <= date_dt]
                            computed_balance = beg_bal + transactions_up_to_date['SignedAmount'].sum()
                            balance_df.at[idx, 'Computed'] = computed_balance
                        
                        balance_df['Difference'] = balance_df['Balance'] - balance_df['Computed']
                        
                        balance_diffs = balance_df[abs(balance_df['Difference']) > 0.01]
                        if not balance_diffs.empty:
                            balance_summary_diffs = balance_diffs['Date'].tolist()
                    
                    # --- Validation Check ---
                    summary_diffs = [d['Category'] for d in summary_data if abs(d['Difference']) > 0.01]
                    
                    if not summary_diffs and not balance_summary_diffs:
                        st.success("✅ PASSED: All extracted values match computed balances (Account Summary and Daily Balance Summary).")
                    else:
                        error_msg = "❌ FAILED: Discrepancies found."
                        if summary_diffs:
                            error_msg += f"\n\n**Account Summary Discrepancies:** {', '.join(summary_diffs)}"
                        if balance_summary_diffs:
                            error_msg += f"\n\n**Daily Balance Summary Discrepancies:** {len(balance_summary_diffs)} date(s) with differences"
                        st.error(error_msg)
                    
                    def format_currency(x):
                        if abs(x) < 0.005:
                            return "$0.00"
                        return "${:,.2f}".format(x)
                    
                    # --- Account Summary Table ---
                    st.subheader("Account Summary Comparison")
                    display_df = summary_df.copy()
                    display_df['Extracted'] = display_df['Extracted'].apply(format_currency)
                    display_df['Computed'] = display_df['Computed'].apply(format_currency)
                    
                    def format_difference_summary(x):
                        if abs(x) < 0.005:
                            return "0.00"
                        return f"{x:,.2f}"
                    display_df['Difference'] = display_df['Difference'].apply(format_difference_summary)
                    st.table(display_df)
                    
                    # --- Transaction Metrics (Bank-specific) ---
                    if bank_name == "US Bank":
                        col1, col2, col3, col4, col5, col6 = st.columns(6)
                        col1.metric("Customer Deposits", f"${computed_customer_deposits:,.2f}")
                        col2.metric("Other Deposits", f"${computed_other_deposits:,.2f}")
                        col3.metric("Card Deposits", f"${computed_card_deposits:,.2f}")
                        col4.metric("Card Withdrawals", f"${computed_card_withdrawals:,.2f}")
                        col5.metric("Other Withdrawals", f"${computed_other_withdrawals:,.2f}")
                        col6.metric("Checks Paid", f"${computed_checks:,.2f}")
                    elif bank_name == "Citizens Bank":
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Total Deposits", f"${computed_deposits:,.2f}")
                        col2.metric("Total Debits", f"${abs(computed_debits):,.2f}")
                        col3.metric("Total Checks", f"${abs(computed_checks):,.2f}")
                        col4.metric("Net Change", f"${(computed_deposits + computed_debits + computed_checks):,.2f}")
                    elif bank_name == "Bank of America":
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Total Deposits", f"${computed_deposits:,.2f}")
                        col2.metric("Total Withdrawals", f"${computed_withdrawals:,.2f}")
                        col3.metric("Total Checks", f"${computed_checks:,.2f}")
                        col4.metric("Total Fees", f"${computed_fees:,.2f}")
                    elif bank_name == "Chase":
                        col1, col2, col3, col4 = st.columns(4)
                        col1.metric("Total Deposits", f"${computed_deposits:,.2f}")
                        col2.metric("Total Withdrawals", f"${abs(computed_withdrawals):,.2f}")
                        col3.metric("Total Checks", f"${abs(computed_checks):,.2f}")
                        col4.metric("Total Fees", f"${abs(computed_fees):,.2f}")
                    
                    # Data Grid
                    st.subheader("Transaction Details")
                    if 'Extraction_Seq' in df.columns:
                        df_sorted = df.sort_values('Extraction_Seq', ascending=True).reset_index(drop=True)
                    else:
                        if 'DateTime' not in df.columns:
                            if 'Date' in df.columns:
                                df['DateTime'] = pd.to_datetime(df['Date'], format='%m/%d/%y', errors='coerce')
                        df_sorted = df.sort_values('DateTime', ascending=True).reset_index(drop=True)
                        df_sorted = df_sorted.drop(columns=['DateTime'], errors='ignore')
                    
                    display_txns = df_sorted.drop(columns=['Extraction_Seq'], errors='ignore')
                    
                    st.dataframe(display_txns, use_container_width=True, height=400)
                    
                    # --- Balance Summary ---
                    if not balance_df.empty:
                        st.subheader("Daily Balance Summary Comparison")
                        balance_display = balance_df.drop(columns=['DateTime'], errors='ignore').copy()
                        balance_display['Balance'] = balance_display['Balance'].apply(format_currency)
                        balance_display['Computed'] = balance_display['Computed'].apply(format_currency)
                        
                        def format_difference(x):
                            if abs(x) < 0.005:
                                return "0.00"
                            return f"{x:,.2f}"
                        balance_display['Difference'] = balance_display['Difference'].apply(format_difference)
                        st.table(balance_display)
                    
                    # Download Buttons
                    col1, col2 = st.columns(2)
                    csv = display_txns.to_csv(index=False).encode('utf-8')
                    col1.download_button("Download as CSV", csv, "bank_transactions.csv", "text/csv", key='download-csv')
                    
                    json_str = display_txns.to_json(orient="records", indent=4)
                    col2.download_button("Download as JSON", json_str, "bank_transactions.json", "application/json", key='download-json')
                    
                else:
                    st.warning("No transactions found.")
                    
        except Exception as e:
            st.error(f"Error processing PDF: {str(e)}")
            st.exception(e)

with st.expander("How It Works"):
    st.markdown("""
    This app automatically identifies the bank from your PDF statement and extracts transactions:
    
    1. **Bank Identification**: Scans the PDF for bank-specific patterns and keywords
    2. **Routing**: Routes to the appropriate parser based on the identified bank
    3. **Extraction**: Extracts transactions using bank-specific patterns
    4. **Validation**: Validates extracted totals against the Account Summary section
    
    **Currently Supported Banks:**
    - U.S. Bank
    - Citizens Bank
    - Bank of America
    - Chase
    
    More banks will be added in the future.
    """)