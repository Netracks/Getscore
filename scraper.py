import os
import requests
import time
import random
from bs4 import BeautifulSoup

# ===== Read from environment (set in GitHub Actions) =====
BASE_URL = os.environ.get("BASE_URL", "https://example.com/search")
BIRTH_DATE = os.environ.get("BIRTH_DATE", "1990-01-01")
START_NUMBER = int(os.environ.get("START_NUMBER", "11000000"))
END_NUMBER = int(os.environ.get("END_NUMBER", "11009999"))
SUCCESS_INDICATOR = os.environ.get("SUCCESS_INDICATOR", "Record found")
REQUEST_DELAY_MIN = float(os.environ.get("REQUEST_DELAY_MIN", "0.5"))
REQUEST_DELAY_MAX = float(os.environ.get("REQUEST_DELAY_MAX", "1.5"))

# Optional – use a session to handle cookies
session = requests.Session()

def check_match(response_text):
    """Return True if the response indicates a successful match."""
    # Customise this based on the actual site
    return SUCCESS_INDICATOR in response_text

def try_number(number):
    """Submit one number + birth date. Returns (found_flag, response_text)."""
    number_str = f"{number:08d}"
    payload = {
        "number": number_str,
        "birthdate": BIRTH_DATE,
        # Add any hidden fields if needed (CSRF, etc.)
    }
    # Use POST or GET – adjust as needed
    resp = session.post(BASE_URL, data=payload)
    # resp = session.get(BASE_URL, params=payload)
    resp.raise_for_status()
    return check_match(resp.text), resp.text

def main():
    print(f"🔍 Searching for birth date: {BIRTH_DATE}")
    print(f"📊 Range: {START_NUMBER:08d} – {END_NUMBER:08d}")

    for num in range(START_NUMBER, END_NUMBER + 1):
        found, response = try_number(num)

        if num % 1000 == 0:
            print(f"🔄 Tried {num:08d}...")

        if found:
            print(f"\n✅ MATCH FOUND! Number = {num:08d}")
            # Save result as a file for the GitHub Actions artifact
            with open("match_result.txt", "w") as f:
                f.write(f"Number: {num:08d}\nBirth date: {BIRTH_DATE}\n")
                f.write("\n--- Full response snippet ---\n")
                f.write(response[:2000])  # truncate for safety
            return 0   # success

        # Polite delay
        time.sleep(random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX))

    # If we finish the loop without finding
    print("❌ No match found in the given range.")
    return 1

if __name__ == "__main__":
    exit(main())
