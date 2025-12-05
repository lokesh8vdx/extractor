import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Wells Fargo Parser (Spatial)", layout="wide")

def parse_amount(amount_str):
    """Cleans and converts amount string to float."""
    if not amount_str: return 0.0
    clean_str = str(amount_str).replace('$', '').replace(',', '').replace(' ', '')
    try:
        return float(clean_str)
    except ValueError:
        return 0.0

def parse_wells_fargo_spatial(pdf_file):
    transactions = []
    current_year = "2025" 
    
    with pdfplumber.open(pdf_file) as pdf:
        # 1. Extract Year
        first_page_text = pdf.pages[0].extract_text()
        match = re.search(r'(20\d{2})', first_page_text)
        if match:
            current_year = match.group(1)
            
        for page_num, page in enumerate(pdf.pages):
            # 2. Extract Words with Position Info
            words = page.extract_words()
            
            # 3. Group words by "Line" (using 'top' coordinate with tolerance)
            # This reconstructs the visual lines that text extraction might scramble
            lines = defaultdict(list)
            for w in words:
                # Round 'top' to nearest integer to group slightly misaligned words
                top_key = round(w['top'])
                lines[top_key].append(w)
            
            # Sort lines by vertical position
            sorted_y = sorted(lines.keys())
            
            for y in sorted_y:
                line_words = lines[y]
                # Sort words in line by x position
                line_words.sort(key=lambda x: x['x0'])
                
                # Reconstruct full text for Regex matching
                full_line_text = " ".join([w['text'] for w in line_words])
                
                # Check if line starts with Date (Transaction Start)
                # Matches 4/1 or 04/01
                date_match = re.match(r'^(\d{1,2}/\d{1,2})', full_line_text)
                
                if date_match:
                    date_str = date_match.group(1)
                    description_parts = []
                    amount = 0.0
                    category = "Unknown"
                    
                    # Iterate words to find Amount based on X-Position
                    # Deposit Zone: approx 400 - 450
                    # Withdrawal Zone: approx 450 - 520
                    # (Calibrated from debug script: Dep Header=404, With Header=458)
                    
                    found_amount = False
                    
                    for w in line_words:
                        text = w['text']
                        x = w['x0']
                        
                        # Is it a potential amount? (Has digits and dot/comma)
                        if re.match(r'^-?[\d,]+\.\d{2}$', text):
                            val = parse_amount(text)
                            
                            # Zone Logic
                            # Widened Deposit Zone leftwards (from 400 to 390) to catch large numbers like 160,000.00
                            if 390 <= x < 455:
                                amount = abs(val)
                                category = "Deposits"
                                found_amount = True
                            # Tightened Withdrawal Zone to avoid capturing Balance (starts approx x=528)
                            elif 455 <= x < 515:
                                amount = -abs(val)
                                category = "Withdrawals"
                                found_amount = True
                            # Ignore Ending Balance column (usually x > 525)
                        
                        # Build Description (words < 400 x)
                        if x < 400 and text != date_str:
                            description_parts.append(text)
                            
                    if found_amount:
                        transactions.append({
                            "Date": f"{date_str}/{current_year}",
                            "Description": " ".join(description_parts).strip(),
                            "Amount": amount,
                            "Category": category,
                            "Source_Page": page_num + 1
                        })
                
                # Handle Multi-line Descriptions
                # If line has no date, but we just added a transaction, append text
                elif transactions and not date_match:
                    # Check if line has words before accessing index
                    if not line_words:
                        continue
                        
                    # Heuristic: If text is in the "Description Zone" (Left side)
                    # and not a header line
                    first_word_x = line_words[0]['x0']
                    if first_word_x < 400:
                        # Filter out header noise
                        if "Date" in full_line_text or "Balance" in full_line_text:
                            continue
                            
                        transactions[-1]['Description'] += " " + full_line_text

    return transactions

# --- UI ---
st.title("📍 Wells Fargo Parser (Spatial)")
st.markdown("Extracts transactions using **X-Coordinate Spatial Logic** (Columns: Date | Desc | [Zone: Credit] | [Zone: Debit]).")

uploaded_file = st.file_uploader("Upload 'April wells' PDF", type=['pdf'])

if uploaded_file:
    with st.spinner("Analyzing spatial layout..."):
        try:
            txns = parse_wells_fargo_spatial(uploaded_file)
            
            if txns:
                st.success(f"Extracted {len(txns)} transactions")
                
                df = pd.DataFrame(txns)
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                df.sort_values('Date', inplace=True)
                
                # Analysis
                total_deposits = df[df['Amount'] > 0]['Amount'].sum()
                total_withdrawals = df[df['Amount'] < 0]['Amount'].sum()
                
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Deposits", f"${total_deposits:,.2f}")
                col2.metric("Total Withdrawals", f"${abs(total_withdrawals):,.2f}")
                col3.metric("Net Flow", f"${(total_deposits + total_withdrawals):,.2f}")
                
                st.subheader("Transaction Ledger")
                st.dataframe(df, use_container_width=True)
                
                # CSV Download
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    "Download CSV",
                    csv,
                    "wells_fargo_spatial_export.csv",
                    "text/csv",
                    key='download-csv'
                )
            else:
                st.warning("No transactions found.")
                
        except Exception as e:
            st.error(f"Error: {str(e)}")
