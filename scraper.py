#!/usr/bin/env python3
"""
Scraper for BCECE[LE] Rank Card 2026.
Directly calls the AJAX endpoint with roll number and DOB.
"""

import os
import sys
import time
import random
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ============================================================
#  CONFIGURATION – MATCHING THE BCECE SITE
# ============================================================

# Direct AJAX endpoint (no need for the HTML page)
BASE_URL = "https://bceceboard.bihar.gov.in/web_RankCard/BLE2026_RANK/BLE_RankPrint.php"

# HTTP method – the AJAX call uses GET
FORM_METHOD = "GET"

# Field names for the API parameters (fixed)
PARAM_ROLL = "roll"
PARAM_DOB = "dob"
PARAM_P = "p"          # always 1 for rank search

# Indicators for failure – these appear when the roll number is not found
FAILURE_INDICATORS = [
    "No record found",
    "Invalid",
    "not found",
    "Please check"
]

# Indicators for success – if any of these appear in the response, it's a match.
# After testing, you can narrow these down.
SUCCESS_INDICATORS = [
    "Rank",
    "Roll No",
    "Candidate Name",
    "Father",
    "Mother"
]

# ============================================================
#  ENVIRONMENT VARIABLES (set by GitHub Actions or command line)
# ============================================================

BIRTH_DAY      = os.environ.get("BIRTH_DAY", "22")
BIRTH_MONTH    = os.environ.get("BIRTH_MONTH", "03")
BIRTH_YEAR     = os.environ.get("BIRTH_YEAR", "2006")
START_NUMBER   = int(os.environ.get("START_NUMBER", "11006500"))
END_NUMBER     = int(os.environ.get("END_NUMBER", "11006520"))
MAX_WORKERS    = int(os.environ.get("MAX_WORKERS", "5"))
DELAY_PER_REQUEST = float(os.environ.get("DELAY_PER_REQUEST", "0.5"))
DEBUG          = os.environ.get("DEBUG", "false").lower() == "true"

# ============================================================
#  GLOBAL STATE
# ============================================================

found_lock = Lock()
found_number = None
session = requests.Session()

# ============================================================
#  HELPER FUNCTIONS
# ============================================================

def check_match(response_text):
    """
    Return True only if the response clearly shows a rank card.
    """
    if not response_text:
        return False

    # 1. If any failure indicator is present, it's NOT a match
    lower_text = response_text.lower()
    for fail in FAILURE_INDICATORS:
        if fail.lower() in lower_text:
            if DEBUG:
                print(f"🚫 Failure indicator '{fail}' found – not a match.")
            return False

    # 2. Look for success indicators – if any are present, it's a match
    for success in SUCCESS_INDICATORS:
        if success.lower() in lower_text:
            if DEBUG:
                print(f"✅ Success indicator '{success}' found – match!")
            return True

    # 3. Additional heuristic: if the response contains a table with data,
    #    but we don't have a specific indicator, assume it's a match if it's longer than 200 chars.
    if len(response_text.strip()) > 200 and ("table" in lower_text or "tr" in lower_text):
        if DEBUG:
            print("⚠️ No explicit indicator, but response looks like a table – assuming match.")
        return True

    if DEBUG:
        print("❌ No success indicators found – assuming no match.")
    return False

def try_number(number):
    """
    Send a GET request to the API with the roll number and DOB.
    Returns (number, found_flag, response_text).
    """
    number_str = f"{number:08d}"
    dob_str = f"{BIRTH_YEAR}-{BIRTH_MONTH}-{BIRTH_DAY}"

    params = {
        PARAM_P: "1",
        PARAM_ROLL: number_str,
        PARAM_DOB: dob_str,
    }

    resp = session.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()

    if DEBUG:
        with open(f"debug_{number_str}.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(f"\n🔎 Request for {number_str}: status={resp.status_code}")

    found = check_match(resp.text)
    return number, found, resp.text

def worker(numbers, progress_counter, progress_lock):
    """Worker thread: process a chunk of numbers."""
    global found_number

    local_session = requests.Session()
    for num in numbers:
        with found_lock:
            if found_number is not None:
                break

        try:
            number, found, response = try_number(num)
            if found:
                with found_lock:
                    if found_number is None:
                        found_number = number
                        with open("match_result.txt", "w") as f:
                            f.write(f"Number: {number:08d}\n")
                            f.write(f"Birth date: {BIRTH_DAY}/{BIRTH_MONTH}/{BIRTH_YEAR}\n")
                            f.write("\n--- Response (first 2000 chars) ---\n")
                            f.write(response[:2000])
                break

            with progress_lock:
                progress_counter[0] += 1
                if progress_counter[0] % 100 == 0:
                    print(f"⏳ Tried {progress_counter[0]} numbers...", end='\r')
                    sys.stdout.flush()

        except requests.exceptions.RequestException as e:
            print(f"\n⚠️ Network error on {num:08d}: {e}")
            time.sleep(DELAY_PER_REQUEST * 2)
        except Exception as e:
            print(f"\n⚠️ Unexpected error on {num:08d}: {e}")

        time.sleep(DELAY_PER_REQUEST + random.uniform(-0.1, 0.1))

def main():
    total = END_NUMBER - START_NUMBER + 1
    print(f"🔍 Searching for birth date: {BIRTH_DAY}/{BIRTH_MONTH}/{BIRTH_YEAR}")
    print(f"📊 Range: {START_NUMBER:08d} – {END_NUMBER:08d} (total {total})")
    print(f"🧵 Using {MAX_WORKERS} threads, delay ~{DELAY_PER_REQUEST}s each")
    print(f"🐛 Debug mode: {DEBUG}")
    print(f"🌐 Target API: {BASE_URL}")

    numbers = list(range(START_NUMBER, END_NUMBER + 1))
    chunk_size = max(1, len(numbers) // MAX_WORKERS)
    chunks = [numbers[i:i + chunk_size] for i in range(0, len(numbers), chunk_size)]

    progress_counter = [0]
    progress_lock = Lock()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(worker, chunk, progress_counter, progress_lock)
            for chunk in chunks
        ]
        for future in as_completed(futures):
            future.result()

    with found_lock:
        if found_number is not None:
            print(f"\n✅ MATCH FOUND! Number = {found_number:08d}")
            print("📄 Result saved to match_result.txt")
            return 0
        else:
            print("\n❌ No match found in the given range.")
            if DEBUG:
                print("💡 Debug HTML files saved as debug_*.html – inspect them.")
            return 1

if __name__ == "__main__":
    sys.exit(main())
