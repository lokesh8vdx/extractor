import pdfplumber

pdf_path = "063025 WellsFargo.pdf"

try:
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            print(f"--- Page {i+1} ---")
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if text:
                print(text)
            else:
                print("[No text extracted]")
            print("\n")
except Exception as e:
    print(f"Error: {e}")

