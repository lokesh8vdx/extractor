import re

# Regex from wells_fargo.py
txn_pattern = re.compile(r'^\s*(\d{2}/\d{2})\s+(?:(\d{2}/\d{2})\s+)?([\d,]+\.\d{2})\s+(.*)$')

lines_to_test = [
    "06/13 2,104.32 Mobile Deposit : Ref Number :409130183545",
    "06/23 990.00 Mobile Deposit : Ref Number :706230145230",
    "06/02 3,232.44 Bret Steel Corpo Labor Alpha Labor CO LLC",
    "06/02 22,621.94 Intuit 45230533 Deposit 250531 524771999789542 Alpha Labor CO, LLC",
    "06/02 50,000.00 Online Transfer From Johnston M Everyday Checking xxxxxx5163 Ref",
    "06/02 73.02 Purchase authorized on 05/30 Wawa 5307 Stuart FL S305150623896321 Card",
    "06/02 200.00 Money Transfer authorized on 05/30 Cash App*Joey Chap Oakland CA",
    "06/02 29.00 < Business to Business ACH Debit - Funding Futures 2118880 Jun 02 8256219323",
    "06/23 06/24 8,135.00 < Business to Business ACH Debit - Fusion Funding Debits Jun 23 NC2009768", # Double date line
]

print("Testing Regex Matches:")
for line in lines_to_test:
    match = txn_pattern.match(line)
    if match:
        print(f"[MATCH] {line}")
        print(f"   Groups: {match.groups()}")
    else:
        print(f"[FAIL]  {line}")

