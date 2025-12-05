import pdfplumber

with pdfplumber.open("April wells  (1).pdf") as pdf:
    page = pdf.pages[1] # Page 2
    tables = page.extract_tables()
    print(f"Found {len(tables)} tables on Page 2")
    for i, table in enumerate(tables):
        print(f"--- Table {i} ---")
        for row in table[:5]: # Print first 5 rows
            print(row)

