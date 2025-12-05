import pdfplumber

with pdfplumber.open("April wells  (1).pdf") as pdf:
    for i, page in enumerate(pdf.pages):
        text = page.extract_text()
        if "160,000.00" in text:
            print(f"Found 160,000.00 on Page {i+1}")
            
            words = page.extract_words()
            for w in words:
                if "160,000.00" in w['text']:
                    print(f"Coords: x={w['x0']:.2f}, top={w['top']:.2f}")
