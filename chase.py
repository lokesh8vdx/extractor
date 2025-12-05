import streamlit as st
import pdfplumber
import pandas as pd
import re
import io
from collections import Counter

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
            # Reduced y_tolerance to handle interleaved hidden text (e.g. "checks paid section" overlapping with check numbers)
            text = page.extract_text(x_tolerance=2, y_tolerance=0.3)
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
            # Updated to allow optional space before slash (e.g. "03 /11")
            balance_pattern = re.compile(r'(\d{0,2}\s?/\d{2})\s+(-?\$?[\d,]+\.\d{2})')

            # Pattern for Checking Summary
            # Matches: Label (text), Optional Count (int), Amount (currency)
            summary_pattern = re.compile(r'^(.*?)\s+(?:(\d+)\s+)?(-?\$?[\d,]+\.\d{2})$')

            current_section = None
            
            for line in lines:
                line = line.strip()
                
                # Global Noise Filtering
                # Skip watermark lines
                if "WM" in line and "bbcd" in line:
                    continue
                if line.startswith("WM") or "%%WM" in line:
                    continue
                
                # Skip hidden text markers if they appear on their own line
                # Also skip "Total Checks Paid" footer and common disclaimer text
                if "*start*" in line or "*end*" in line or "Total Checks Paid" in line:
                    continue
                
                if "If you see a description" in line or "return the check to you" in line:
                    continue
                
                if "All of your recent checks" in line or "An image of this check" in line:
                    continue
                
                # Additional specific filter for broken disclaimer line
                if "one of your previous statements" in line:
                    continue
                
                # Filter out single letter noise lines like "d d", "c c"
                if re.match(r'^([a-zA-Z]\s)+[a-zA-Z]$', line) and len(line) < 10:
                    continue

                # Skip "Total ..." footer lines for various sections
                if line.startswith("Total ") and ("Deposits" in line or "Withdrawals" in line or "Fees" in line or "Purchases" in line or "Credits" in line):
                    continue
                
                if "ATM & Debit Card Totals" in line:
                    continue

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
                            # Remove potential spaces captured by regex
                            date = date.replace(' ', '')
                            
                            # Fix date year if needed
                            if date.startswith('/'):
                                if balances:
                                    last_date = balances[-1]['Date']
                                    # Handle potential full date format MM/DD/YY in last_date
                                    parts = last_date.split('/')
                                    last_month = parts[0]
                                    last_day = parts[1]
                                    
                                    current_day_str = date.replace('/', '')
                                    
                                    try:
                                        cur_d = int(current_day_str)
                                        lst_d = int(last_day)
                                        lst_m = int(last_month)
                                        
                                        # Heuristic: If current day is significantly smaller than last day, 
                                        # it's likely the next month (e.g. 28 -> 02)
                                        if cur_d < lst_d:
                                            new_month = lst_m + 1
                                            if new_month > 12: new_month = 1
                                            date = f"{new_month:02d}{date}"
                                        else:
                                            date = f"{last_month}{date}"
                                    except ValueError:
                                        date = f"{last_month}{date}"
                                else:
                                    date = f"04{date}" # Fallback
                            else:
                                # Sequential Validation Logic
                                # Since Daily Ending Balances must be chronological,
                                # we check if the current date seems to "jump back" in time (e.g. 03/10 -> 02/11).
                                # This handles noise like "balance2/11" being parsed as "2/11" instead of "03/11".
                                if balances:
                                    try:
                                        last_date = balances[-1]['Date']
                                        last_m_str, last_d_str = last_date.split('/')
                                        last_m = int(last_m_str)
                                        
                                        # Clean current date parts
                                        cur_parts = date.split('/')
                                        if len(cur_parts) == 2:
                                            cur_m = int(cur_parts[0])
                                            
                                            # Check for backward month jump (excluding Dec -> Jan)
                                            # If cur_m < last_m and not (last_m == 12 and cur_m == 1):
                                                # It's likely a corrupted month digit.
                                                # We assume it belongs to the same month (or next, but rarely skips back)
                                                # Since 11 > 10 (in 03/10 -> 2/11 example), using last_m (03) makes it 03/11 which is valid.
                                                
                                                # But what if it SHOULD be next month? e.g. 03/31 -> 2/01 (noise for 04/01)?
                                                # If we force 03/01, it's still < 03/31.
                                                # So we might need to check days too.
                                                
                                                # Simple robust fix for "balance2/11" case:
                                                # If cur_m is clearly wrong (backwards), try last_m.
                                                # If changing to last_m makes it chronological (or close), use it.
                                                
                                                # Update date to use last_m
                                            date = f"{last_m:02d}/{cur_parts[1]}"
                                    except (ValueError, IndexError):
                                        pass
                                
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
                
                # HANDLE MULTI-LINE DESCRIPTIONS (Simplified Logic from boa.py)
                # If a line doesn't start with a date but we just added a transaction,
                # it's likely a continuation of the previous description.
                elif transactions and not re.match(r'\d{2}/\d{2}', line) and \
                     not (current_section == "Checks Paid" and re.match(r'^\d+', line)) and \
                     current_section not in ["Daily Ending Balance", "Checking Summary"]:
                    
                    # Ensure we don't append lines from a new page to a previous page's transaction
                    if transactions[-1]['Page'] != page_num:
                        continue
                    
                    # Ensure we don't append lines if the section has changed (e.g. previous txn was Deposit, now we are in Checks Paid header)
                    if current_section != transactions[-1]['Type']:
                        continue

                    # Skip if it looks like a balance summary line (Chase specific noise)
                    if "$" in line and "Balance" in line:
                        continue

                    # Clean debug markers from the line (e.g. *end*deposits and additions ...)
                    # Only remove the marker and the section name, keeping potential transaction text
                    if "*start*" in line or "*end*" in line:
                        # Regex to remove *start/end* followed by text, but careful not to eat transaction info
                        # Matches *tag* followed by non-digits until a digit or end of line
                        line = re.sub(r'\*(?:start|end)\*[^\d]+', '', line).strip()
                        if not line:
                            continue

                    # Skip potential header/footer junk and noise markers
                    if "DATE DESCRIPTION" in line or \
                       "DATE AMOUNT" in line or \
                       "CHECK NO." in line or \
                       "Account Number" in line or \
                       re.match(r'^[\d\s]+$', line) or \
                       ("through" in line and re.search(r'\d{4}', line)):
                        continue

                    # Clean up trailing "DATE AMOUNT" if it got appended
                    if transactions and transactions[-1]["Description"].endswith(" DATE AMOUNT"):
                         transactions[-1]["Description"] = transactions[-1]["Description"].replace(" DATE AMOUNT", "")


                    # Skip fee explanation text noise
                    if "Excess Transaction Fees" in line or "Your total transactions" in line:
                        continue
                    if "You can use" in line or "Paper checks written" in line or "Deposits and withdrawals" in line:
                        continue
                    if "Monthly Service Fee of either" in line or "sum of the Monthly Service Fee" in line:
                        continue
                    
                    # Prevent duplication of Fee Description if line matches exactly (case-insensitive)
                    if transactions[-1]["Description"].lower() == line.lower():
                        continue
                        
                    # Special case for Monthly Service Fee which often repeats in footer
                    if "Monthly Service Fee" in transactions[-1]["Description"] and "Monthly Service Fee" in line:
                        continue

                    # Skip lines that are just bullet points or special chars
                    if re.match(r'^[\W_]+$', line):
                        continue

                    # Skip tracking ID noise (long alphanumeric strings with hyphens)
                    # Matches "Digits-Alphanum" (e.g. 8979617741571-RAIFtklQ00000kQs20)
                    if re.search(r'\d+-[A-Za-z0-9]+', line):
                        continue
                    # Matches "Alphanum-Digits" (e.g. 4De20Fca304F-0000003)
                    if re.search(r'[A-Za-z0-9]+-\d+', line) and len(line) > 15:
                        continue
                        
                    # Append to previous transaction description
                    last_txn = transactions[-1]
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
                
                # --- Account Summary Comparison Table (like boa.py) ---
                st.subheader("Account Summary Comparison")
                
                # Extract summary values from checking_summary DataFrame
                extracted_summary = {}
                if not summary_df.empty:
                    # Look for common summary fields in the Description column
                    for _, row in summary_df.iterrows():
                        desc = str(row['Description']).lower()
                        amount = row['Amount']
                        
                        if 'opening' in desc or 'beginning' in desc:
                            extracted_summary['Beginning Balance'] = amount
                        elif 'closing' in desc or 'ending' in desc:
                            extracted_summary['Ending Balance'] = amount
                        elif 'deposit' in desc or 'additions' in desc:
                            extracted_summary['Deposits'] = abs(amount)
                        elif 'withdrawal' in desc or 'debit' in desc:
                            # Sum all withdrawal types (ATM, Electronic, Other, etc.)
                            if 'Withdrawals' not in extracted_summary:
                                extracted_summary['Withdrawals'] = 0.0
                            extracted_summary['Withdrawals'] += abs(amount)
                        elif 'check' in desc:
                            extracted_summary['Checks'] = abs(amount)
                        elif 'fee' in desc:
                            extracted_summary['Fees'] = abs(amount)
                
                # Calculate Computed Values from transactions
                # Use abs() sum to ensure positive magnitude for comparison
                computed_deposits = abs(df[df['Type'] == 'Deposit']['Amount'].sum())
                computed_atm = abs(df[df['Type'] == 'ATM & Debit Withdrawal']['Amount'].sum())
                computed_electronic = abs(df[df['Type'] == 'Electronic Withdrawal']['Amount'].sum())
                computed_checks = abs(df[df['Type'] == 'Checks Paid']['Amount'].sum())
                computed_other = abs(df[df['Type'] == 'Other Withdrawal']['Amount'].sum())
                # Total withdrawals = sum of all withdrawal types (ATM, Electronic, Other)
                computed_withdrawals = computed_atm + computed_electronic + computed_other
                computed_fees = abs(df[df['Type'] == 'Fee']['Amount'].sum())
                
                # Beginning balance is not computed from transactions, so we take extracted or 0
                beg_bal = extracted_summary.get('Beginning Balance', 0.0)
                
                # Compute Ending Balance
                # Note: Following boa.py pattern - add all values together
                # If withdrawals/checks/fees are negative in the data, adding them will subtract
                # If they're positive, we subtract them explicitly
                # Since we standardized to positive magnitudes above:
                # Balance = Beg + Deposits - Withdrawals - Checks - Fees
                computed_ending = beg_bal + computed_deposits - computed_withdrawals - computed_checks - computed_fees
                
                # Create summary comparison table
                summary_data = [
                    {
                        "Category": "Beginning Balance", 
                        "Extracted": extracted_summary.get('Beginning Balance', 0.0), 
                        "Computed": beg_bal, 
                        "Difference": 0.0
                    },
                    {
                        "Category": "Deposits/Credits", 
                        "Extracted": extracted_summary.get('Deposits', 0.0), 
                        "Computed": computed_deposits, 
                        "Difference": extracted_summary.get('Deposits', 0.0) - computed_deposits
                    },
                    {
                        "Category": "Withdrawals/Debits", 
                        "Extracted": extracted_summary.get('Withdrawals', 0.0), 
                        "Computed": computed_withdrawals, 
                        "Difference": extracted_summary.get('Withdrawals', 0.0) - computed_withdrawals
                    },
                    {
                        "Category": "Checks Paid", 
                        "Extracted": extracted_summary.get('Checks', 0.0), 
                        "Computed": computed_checks, 
                        "Difference": extracted_summary.get('Checks', 0.0) - computed_checks
                    },
                    {
                        "Category": "Fees", 
                        "Extracted": extracted_summary.get('Fees', 0.0), 
                        "Computed": computed_fees, 
                        "Difference": extracted_summary.get('Fees', 0.0) - computed_fees
                    },
                    {
                        "Category": "Ending Balance", 
                        "Extracted": extracted_summary.get('Ending Balance', 0.0), 
                        "Computed": computed_ending, 
                        "Difference": extracted_summary.get('Ending Balance', 0.0) - computed_ending
                    },
                ]
                
                summary_comparison_df = pd.DataFrame(summary_data)
                
                # --- 2. Daily Ledger Analysis (Validation) ---
                ledger_analysis_df = pd.DataFrame()
                if not balance_df.empty:
                    # Standardize Date Format for Processing
                    # balance_df['Date'] is already MM/DD, need to handle year and sorting
                    
                    # Determine Year from Transactions if possible
                    year = "25" # Default
                    if 'Date' in df.columns and not df.empty:
                        first_date = df.iloc[0]['Date']
                        try:
                            parts = first_date.split('/')
                            if len(parts) == 3:
                                year = parts[2]
                            # If date is MM/DD, we might need external context or assume current year
                        except:
                            pass
                    
                    # Helper to convert date string to datetime for sorting
                    def to_datetime(date_str):
                        try:
                            if isinstance(date_str, str):
                                if date_str.count('/') == 1:
                                    return pd.to_datetime(f"{date_str}/{year}", format='%m/%d/%y', errors='coerce')
                                return pd.to_datetime(date_str, format='%m/%d/%y', errors='coerce')
                            return pd.NaT
                        except:
                            return pd.NaT

                    # Create copies to avoid SettingWithCopyWarning
                    balance_calc_df = balance_df.copy()
                    df_calc = df.copy()

                    balance_calc_df['DateTime'] = balance_calc_df['Date'].apply(to_datetime)
                    df_calc['DateTime'] = df_calc['Date'].apply(to_datetime)
                    
                    # Sort by date
                    balance_calc_df = balance_calc_df.sort_values('DateTime')
                    df_calc = df_calc.sort_values('DateTime')
                    
                    ledger_analysis = []
                    
                    for idx, row in balance_calc_df.iterrows():
                        l_date = row['DateTime']
                        l_balance = row['Amount']
                        
                        if pd.isnull(l_date):
                            continue
                            
                        # Calculate computed balance for this date
                        # Balance = Beginning Balance + (Deposits - Withdrawals - Checks - Fees) up to this date
                        relevant_txns = df_calc[df_calc['DateTime'] <= l_date]
                        
                        current_bal = beg_bal
                        for _, txn in relevant_txns.iterrows():
                            amt = txn['Amount']
                            t_type = txn['Type']
                            
                            if t_type == 'Deposit':
                                current_bal += amt
                            else:
                                current_bal -= amt
                        
                        diff = l_balance - current_bal
                        
                        ledger_analysis.append({
                            "Date": row['Date'],
                            "Extracted Balance": l_balance,
                            "Computed Balance": current_bal,
                            "Difference": diff
                        })
                    
                    ledger_analysis_df = pd.DataFrame(ledger_analysis)

                # --- Validation Check (PASSED/FAILED Message) ---
                summary_diffs = [d['Category'] for d in summary_data if abs(d['Difference']) > 0.01]
                
                ledger_diffs = []
                if not ledger_analysis_df.empty:
                    ledger_diffs = ledger_analysis_df[abs(ledger_analysis_df['Difference']) > 0.01]['Date'].tolist()
                
                if not summary_diffs and not ledger_diffs:
                    st.success("✅ PASSED: All extracted values match computed balances.")
                else:
                    error_msg = "❌ FAILED: Discrepancies found."
                    if summary_diffs:
                        error_msg += f"\n\n**Summary Discrepancies:** {', '.join(summary_diffs)}"
                    if ledger_diffs:
                        error_msg += f"\n\n**Daily Ledger Discrepancies (Dates):** {', '.join(str(d) for d in ledger_diffs)}"
                    st.error(error_msg)
                
                # Format columns for display
                def format_currency(x):
                    return "${:,.2f}".format(x)

                def format_number(x):
                    return "{:,.2f}".format(x)
                
                display_df = summary_comparison_df.copy()
                display_df['Extracted'] = display_df['Extracted'].apply(format_currency)
                display_df['Computed'] = display_df['Computed'].apply(format_currency)
                display_df['Difference'] = display_df['Difference'].apply(format_number)
                
                st.table(display_df)
                
                # Show original Checking Summary if available
                if not summary_df.empty:
                    with st.expander("Raw Checking Summary (from PDF)"):
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
                
                # --- Daily Ledger Analysis ---
                if not ledger_analysis_df.empty:
                    st.divider()
                    st.subheader("Daily Ledger Balances Analysis")
                    
                    # Format for display
                    display_ledger = ledger_analysis_df.copy()
                    display_ledger['Extracted Balance'] = display_ledger['Extracted Balance'].apply(format_currency)
                    display_ledger['Computed Balance'] = display_ledger['Computed Balance'].apply(format_currency)
                    # Difference shown as raw number
                    st.table(display_ledger)
                    
                    csv_bal = ledger_analysis_df.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "Download Ledger Analysis CSV",
                        csv_bal,
                        "bank_statement_ledger_analysis.csv",
                        "text/csv",
                        key='download-bal-csv'
                    )
                elif not balance_df.empty:
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
