def identify_bank_original(text):
    """Scans text for bank fingerprints."""
    text_lower = text.lower()
    if "chase" in text_lower and "jpmorgan" in text_lower:
        return "Chase"
    if "wells fargo" in text_lower:
        return "Wells Fargo"
    if "bank of america" in text_lower:
        return "Bank of America"
    return "Unknown"

def identify_bank_fixed(text):
    """Scans text for bank fingerprints."""
    text_lower = text.lower()
    
    # Stronger Wells Fargo checks
    if "wellsfargo.com" in text_lower or "1-800-call-wells" in text_lower:
        return "Wells Fargo"

    if "chase" in text_lower and "jpmorgan" in text_lower:
        return "Chase"
    if "wells fargo" in text_lower:
        return "Wells Fargo"
    if "bank of america" in text_lower:
        return "Bank of America"
    return "Unknown"

# Load text from debug output
with open("/Users/lokeshkatta/.cursor/projects/Users-lokeshkatta-Desktop-Adhoc/agent-tools/d6dcdcc2-81f6-4860-a6ec-0ba59c5cccab.txt", "r") as f:
    text = f.read()

# Extract page 1 text (approximate)
page_1_end = text.find("--- Page 2 ---")
page_1_text = text[:page_1_end]

print(f"Original Logic Result: {identify_bank_original(page_1_text)}")
print(f"Fixed Logic Result:    {identify_bank_fixed(page_1_text)}")

