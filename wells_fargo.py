import streamlit as st
import pdfplumber
import pandas as pd
import re
from collections import defaultdict

st.set_page_config(page_title="Wells Fargo Parser", layout="wide")

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
    if "wellsfargo.com" in text_lower:
        return "Wells Fargo"
    if "wells fargo" in text_lower:
        return "Wells Fargo"
    return "Unknown"

def extract_year_from_header(text):
    """Tries to find a 4-digit year in the first page text."""
    match = re.search(r'(20\d{2})', text)
    return match.group(1) if match else "2025"

def extract_beginning_balance(text):
    """Extracts beginning balance from the summary section."""
    # Look for "Beginning balance" followed by currency
    match = re.search(r'Beginning balance', text, re.IGNORECASE)
    if match:
        # Search in the text following the match
        post_text = text[match.end():]
        # Find first currency amount (allowing for newlines and spaces)
        amount_match = re.search(r'\$\s?([\d,]+\.\d{2})', post_text)
        if amount_match:
            return parse_amount(amount_match.group(1))
    return None

# --- STRATEGY 1: WELLS FARGO (REGEX / STREAM) ---
def parse_wells_fargo_regex(pdf, current_year):
    """
    Parses Wells Fargo statements using Regex on text stream.
    Best for: Standard checking accounts with clear columns.
    """
    transactions = []
    balances = []
    
    # Regex for Standard Transactions: Date -> [Optional Effective Date] -> Amount -> Description
    txn_pattern = re.compile(r'^\s*(\d{2}/\d{2})\s+(?:(\d{2}/\d{2})\s+)?([\d,]+\.\d{2})\s+(.*)$')
    
    # Regex for Checks: Check Number -> Amount -> Date (Multi-column support)
    check_pattern = re.compile(r'(\d+)\s+([\d,]+\.\d{2})\s+(\d{2}/\d{2})')

    # Regex for Balance History: (MM/DD) (Amount)
    balance_pattern = re.compile(r'(\d{2}/\d{2})\s+([\d,]+\.\d{2})')
    
    current_section = "Uncategorized"
    
    try:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if not text: continue
            
            lines = text.split('\n')
            
            for line in lines:
                line = line.strip()
                line_lower = line.lower()
                
                # 1. DETECT SECTION HEADERS
                if "credits" in line_lower or "deposits" in line_lower:
                    current_section = "Credits"
                elif "debits" in line_lower or "withdrawals" in line_lower:
                    current_section = "Debits"
                elif "checks paid" in line_lower:
                    current_section = "Checks Paid"
                elif "daily ledger balance" in line_lower or "daily ending balance" in line_lower:
                    current_section = "Balance History"
                elif "average daily" in line_lower:
                     current_section = "Footer"
                
                # Skip noisy header/footer lines
                if "Page" in line or "Account number" in line or "Wells Fargo" in line:
                    continue

                # 2. HANDLE BALANCE HISTORY SECTION
                if current_section == "Balance History":
                    matches = balance_pattern.findall(line)
                    if matches:
                        for m in matches:
                            b_date, b_amount_str = m
                            if "Date" in b_date: continue
                            balances.append({
                                "Date": f"{b_date}/{current_year}",
                                "Balance": parse_amount(b_amount_str),
                                "Bank": "Wells Fargo"
                            })
                    continue 
                
                if current_section == "Footer":
                    continue

                # 3. MATCH CHECKS (Specific Format, supports multi-column)
                if current_section == "Checks Paid":
                    matches = check_pattern.findall(line)
                    if matches:
                        for m in matches:
                            check_num, amount_str, date_part = m
                            amount = parse_amount(amount_str)
                            
                            transactions.append({
                                "Date": f"{date_part}/{current_year}",
                                "Description": f"Check #{check_num}",
                                "Amount": -abs(amount), # Checks are withdrawals
                                "Category": "Checks Paid",
                                "Bank": "Wells Fargo"
                            })
                        continue

                # 4. MATCH STANDARD TRANSACTIONS
                match = txn_pattern.match(line)
                if match:
                    date_part_1, date_part_2, amount_str, desc = match.groups()
                    
                    # Use Posted Date (2nd date) if present, else 1st date
                    date_part = date_part_2 if date_part_2 else date_part_1
                    
                    amount = parse_amount(amount_str)
                    
                    # Apply Sign based on Section
                    if current_section in ["Debits", "Checks Paid"]:
                        amount = -abs(amount)
                    else:
                        amount = abs(amount)

                    transactions.append({
                        "Date": f"{date_part}/{current_year}",
                        "Description": desc.strip(),
                        "Amount": amount,
                        "Category": current_section,
                        "Bank": "Wells Fargo"
                    })
                
                # 5. HANDLE MULTI-LINE DESCRIPTIONS
                elif transactions and len(line) > 0:
                    # Don't append if we are in non-transaction sections
                    if current_section in ["Checks Paid", "Balance History", "Footer"]:
                        continue
                        
                    is_summary = any(k in line_lower for k in ["total", "balance", "summary", "credits", "debits", "checks paid"])
                    if not is_summary:
                        transactions[-1]["Description"] += " " + line
                        
    except Exception as e:
        print(f"Regex strategy warning: {e}")
        
    return transactions, balances

# --- STRATEGY 2: WELLS FARGO (SPATIAL / X-COORDINATE) ---
def parse_wells_fargo_spatial(pdf, current_year):
    """
    Parses Wells Fargo statements using X-Coordinates.
    Best for: Complex layouts where text extraction scrambles columns.
    """
    transactions = []
    balances = []
    
    try:
        for page_num, page in enumerate(pdf.pages):
            # 1. Extract Words with Position Info
            words = page.extract_words()
            
            # 2. Group words by "Line" (using 'top' coordinate with tolerance)
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
                    found_amount = False
                    
                    for w in line_words:
                        text = w['text']
                        x = w['x0']
                        
                        # Is it a potential amount? (Has digits and dot/comma)
                        if re.match(r'^-?[\d,]+\.\d{2}$', text):
                            val = parse_amount(text)
                            
                            # Zone Logic (Calibrated for Wells Fargo)
                            # Deposit Zone: approx 390 - 455
                            if 390 <= x < 455:
                                amount = abs(val)
                                category = "Deposits"
                                found_amount = True
                            # Withdrawal Zone: approx 455 - 515
                            elif 455 <= x < 515:
                                amount = -abs(val)
                                category = "Withdrawals"
                                found_amount = True
                            # Balance Zone: approx x > 515 (Running Balance)
                            elif x >= 515:
                                # Handled below
                                pass 

                        # Build Description (words < 400 x)
                        if x < 400 and text != date_str:
                            description_parts.append(text)
                            
                    if found_amount:
                        transactions.append({
                            "Date": f"{date_str}/{current_year}",
                            "Description": " ".join(description_parts).strip(),
                            "Amount": amount,
                            "Category": category,
                            "Bank": "Wells Fargo",
                            "Source_Strategy": "Spatial"
                        })
                        
                        # 2b. Look for Balance in the same line (Rightmost word)
                        for w in line_words:
                             if w['x0'] > 515 and re.match(r'^-?[\d,]+\.\d{2}$', w['text']):
                                 b_val = parse_amount(w['text'])
                                 balances.append({
                                     "Date": f"{date_str}/{current_year}",
                                     "Balance": b_val,
                                     "Bank": "Wells Fargo"
                                 })
                                 break # Only one balance per line
                
                # Handle Multi-line Descriptions
                elif transactions and not date_match:
                    if not line_words: continue
                        
                    # Heuristic: If text is in the "Description Zone" (Left side)
                    first_word_x = line_words[0]['x0']
                    if first_word_x < 400:
                        # Filter out header noise
                        if "Date" in full_line_text or "Balance" in full_line_text:
                            continue
                            
                        transactions[-1]['Description'] += " " + full_line_text

    except Exception as e:
        print(f"Spatial strategy warning: {e}")

    return transactions, balances

# --- STRATEGY 3: WELLS FARGO MASTER SWITCH ---
def parse_wells_fargo(pdf, current_year):
    """
    Tries Regex strategy first. If no transactions found, switches to Spatial strategy.
    """
    # 1. Try Standard Regex
    txns, bals = parse_wells_fargo_regex(pdf, current_year)
    
    if txns:
        st.info(f"Used Standard Regex Strategy (Found {len(txns)} txns)")
        return txns, bals
    
    # 2. Fallback to Spatial
    st.warning("Standard Regex found no transactions. Switching to Spatial Logic...")
    try:
        txns, bals = parse_wells_fargo_spatial(pdf, current_year)
        if txns:
            st.success(f"Spatial Logic Successful (Found {len(txns)} txns)")
            return txns, bals
    except Exception as e:
        st.error(f"Spatial Logic Failed: {e}")
        
    return [], []

# --- MAIN ROUTER ---
def process_pdf(pdf_file):
    try:
        # Ensure we start at the beginning of the file stream
        if hasattr(pdf_file, 'seek'):
            pdf_file.seek(0)
            
        with pdfplumber.open(pdf_file) as pdf:
            if not pdf.pages:
                return [], [], 0.0
                
            # 1. Identify Bank & Year from Page 1
            first_page_text = pdf.pages[0].extract_text()
            if not first_page_text:
                # Try page 2 if page 1 is empty (e.g. scan cover sheet)
                if len(pdf.pages) > 1:
                    first_page_text = pdf.pages[1].extract_text()
                else:
                    return [], [], 0.0

            bank_name = identify_bank(first_page_text)
            year = extract_year_from_header(first_page_text)
            start_bal = extract_beginning_balance(first_page_text) or 0.0
            
            st.write(f"**Detected:** {bank_name} ({year})")
            if start_bal:
                st.write(f"**Beginning Balance:** ${start_bal:,.2f}")
            
            # 2. Route to Strategy
            if bank_name == "Wells Fargo":
                txns, bals = parse_wells_fargo(pdf, year)
                return txns, bals, start_bal
            elif bank_name == "Unknown":
                # If not explicitly identified but user uploaded it to this tool, we can try Wells Fargo by default or warn
                 st.warning("Could not auto-detect Wells Fargo. Attempting Wells Fargo parser anyway...")
                 txns, bals = parse_wells_fargo(pdf, year)
                 return txns, bals, start_bal
            else:
                st.error("Bank format not recognized (Only Wells Fargo supported)")
                return [], [], 0.0
                
    except Exception as e:
        # Log the error but don't crash the app; the UI loop will handle it
        raise e

# --- UI ---
st.title("🤖 Wells Fargo Statement Parser")
st.markdown("Automatically detects and extracts data from Wells Fargo PDF statements.")

uploaded_files = st.file_uploader("Upload Wells Fargo PDF Statements", type=['pdf'], accept_multiple_files=True)

if uploaded_files:
    all_txns = []
    all_balances = []
    file_start_bals = []
    
    for file in uploaded_files:
        with st.expander(f"Processing {file.name}", expanded=True):
            try:
                with st.spinner(f"Parsing {file.name}..."):
                    txns, bals, s_bal = process_pdf(file)
                    
                    if txns:
                        all_txns.extend(txns)
                        st.success(f"Extracted {len(txns)} transactions")
                        
                        # Track start balance with the earliest transaction date in this file
                        # We need to temporarily parse dates to find the min
                        temp_dates = [pd.to_datetime(t['Date'], errors='coerce') for t in txns]
                        valid_dates = [d for d in temp_dates if pd.notnull(d)]
                        if valid_dates:
                             min_date = min(valid_dates)
                             file_start_bals.append({'date': min_date, 'balance': s_bal})
                    else:
                        st.warning(f"No transactions found in {file.name}.")
                    
                    if bals:
                        all_balances.extend(bals)
                        st.info(f"Extracted {len(bals)} balance records")
                        
            except Exception as e:
                st.error(f"Error processing {file.name}: {str(e)}")

    
    # --- TRANSACTIONS ANALYSIS ---
    if all_txns:
        df = pd.DataFrame(all_txns)
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df.sort_values('Date', inplace=True)
        
        st.divider()
        st.header("Transaction Analysis")
        
        # Calculation Logic
        total_deposits = df[df['Amount'] > 0]['Amount'].sum()
        
        # 1. Grand Total Withdrawals (Everything negative)
        total_withdrawals = df[df['Amount'] < 0]['Amount'].sum()
        
        # 2. Total Checks (Subset of withdrawals)
        # Checks are identified by 'Category' containing 'Check' or 'Checks Paid'
        check_mask = df['Category'].str.contains('Check', case=False, na=False)
        total_checks = df[check_mask]['Amount'].sum()
        
        # 3. Debits Excluding Checks (The difference)
        total_debits_excl_checks = total_withdrawals - total_checks
        
        # Display Metrics
        col1, col2, col3, col4 = st.columns(4)
        
        col1.metric("Total Deposits", f"${total_deposits:,.2f}")
        col2.metric("Debits (Excl. Checks)", f"${abs(total_debits_excl_checks):,.2f}")
        col3.metric("Total Checks", f"${abs(total_checks):,.2f}")
        col4.metric("Total Withdrawals", f"${abs(total_withdrawals):,.2f}")
        
        st.subheader("Transaction Ledger")
        st.dataframe(df, use_container_width=True)
        
        # CSV Download
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "Download CSV",
            csv,
            "wells_fargo_export.csv",
            "text/csv",
            key='download-csv'
        )

    # --- DAILY BALANCE ANALYSIS ---
    if all_balances:
        st.divider()
        st.header("Daily Ending Balances")
        
        bal_df = pd.DataFrame(all_balances)
        bal_df['Date'] = pd.to_datetime(bal_df['Date'], errors='coerce')
        bal_df.sort_values('Date', inplace=True)
        
        # Compute Running Balance logic
        if all_txns:
             # 1. Determine Global Start Balance
             global_start_bal = 0.0
             if file_start_bals:
                 # Sort by date
                 file_start_bals.sort(key=lambda x: x['date'])
                 global_start_bal = file_start_bals[0]['balance']
             
             st.caption(f"Computed columns based on detected Beginning Balance: **${global_start_bal:,.2f}**")

             # 2. Aggregate Transactions by Day
             txn_df = pd.DataFrame(all_txns)
             txn_df['Date'] = pd.to_datetime(txn_df['Date'], errors='coerce')
             
             # Sum amount per day
             daily_change = txn_df.groupby('Date')['Amount'].sum().reset_index()
             daily_change.sort_values('Date', inplace=True)
             
             # 3. Calculate Running Balance
             daily_change['Computed Balance'] = global_start_bal + daily_change['Amount'].cumsum()
             
             # 4. Merge with Extracted Balances
             # We merge on Date. 
             merged_df = pd.merge(bal_df, daily_change[['Date', 'Computed Balance']], on='Date', how='outer')
             merged_df.sort_values('Date', inplace=True)
             
             # Fill forward the computed balance (balance doesn't change on days with no txns)
             merged_df['Computed Balance'] = merged_df['Computed Balance'].ffill()
             # If starts with NaN (dates before first txn), fill with global start
             merged_df['Computed Balance'] = merged_df['Computed Balance'].fillna(global_start_bal)
             
             # Fill extracted balance NaNs with None/NaN or leave as is?
             # The user wants to compare.
             
             # Calculate Difference (only where we have extracted balance)
             merged_df['Difference'] = merged_df['Balance'] - merged_df['Computed Balance']
             
             # Formatting for display
             # Only show relevant columns
             display_cols = ['Date', 'Balance', 'Computed Balance', 'Difference']
             
             # Highlight differences
             def highlight_diff(row):
                 try:
                     if pd.notnull(row['Difference']) and abs(row['Difference']) > 0.01:
                         return ['background-color: #ffcccc'] * len(row)
                 except: pass
                 return [''] * len(row)

             st.dataframe(merged_df[display_cols].style.apply(highlight_diff, axis=1).format("{:.2f}", subset=['Balance', 'Computed Balance', 'Difference']), use_container_width=True)
             
        else:
            st.dataframe(bal_df, use_container_width=True)
