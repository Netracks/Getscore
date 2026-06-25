#!/usr/bin/env python3
"""
Scraper for finding an 8‑digit number that matches a given birth date.
The birth date is entered via three dropdown selects (day, month, year).
The script fetches the form page, extracts any CSRF token, then tries numbers
in parallel using a thread pool.
"""

import os
import sys
import time
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

import requests
from bs4 import BeautifulSoup

# ============================================================
#  CONFIGURATION – CHANGE THESE TO MATCH YOUR TARGET WEBSITE
# ============================================================

# The URL of the page that contains the form (not necessarily the action)
# If the form submits to the same URL, just set this to the page URL.
BASE_URL = "https://bceceboard.bihar.gov.in/web_RankCard/BLE2026_RANK/BLE_Rank.php"   # <-- CHANGE ME

# Form field names – inspect the HTML to get these.
FIELD_NUMBER = "number"           # name of the input for the 8-digit number
FIELD_DAY    = "day"              # name of the day <select>
FIELD_MONTH  = "month"            # name of the month <select>
FIELD_YEAR   = "year"             # name of the year <select>

# HTTP method: 'POST' or 'GET'
FORM_METHOD = "POST"              # change to "GET" if needed

# Hidden field name for CSRF token (if any). Set to None if not used.
CSRF_FIELD_NAME = "csrf_token"    # change or set to None

# Indicator(s) that a match was found. Can be a string or list of strings.
# The script will check if any of these appear in the response text.
SUCCESS_INDICATORS = ["Record found", "Details found", "Match"]   # <-- adjust

# ============================================================
#  ENVIRONMENT VARIABLES (set by GitHub Actions or command line)
# ============================================================

BIRTH_DAY      = os.environ.get("BIRTH_DAY", "1")
BIRTH_MONTH    = os.environ.get("BIRTH_MONTH", "1")
BIRTH_YEAR     = os.environ.get("BIRTH_YEAR", "1990")
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
session = requests.Session()          # main session for fetching CSRF token

# ============================================================
#  HELPER FUNCTIONS
# ============================================================

def get_csrf_token():
    """
    Fetch the form page, parse it, and return the CSRF token value.
    Returns None if not found or if CSRF_FIELD_NAME is None.
    """
    if CSRF_FIELD_NAME is None:
        return None
    try:
        resp = session.get(BASE_URL, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": CSRF_FIELD_NAME})
        if token_input:
            return token_input.get("value")
        else:
            # Some sites put the token in a meta tag or as a data attribute
            # You can extend this logic if needed.
            return None
    except Exception as e:
        print(f"⚠️ Failed to fetch CSRF token: {e}")
        return None

def check_match(response_text):
    """
    Return True if any success indicator is present in the response.
    Also checks for common patterns like 'found' in a table.
    """
    if not response_text:
        return False
    lower_text = response_text.lower()
    for indicator in SUCCESS_INDICATORS:
        if indicator.lower() in lower_text:
            return True
    # Additional heuristic: look for a table row with data (optional)
    if "found" in lower_text and ("record" in lower_text or "details" in lower_text):
        return True
    return False

def try_number(number, csrf_token=None):
    """
    Submit one number + birth date. Returns (number, found_flag, response_text).
    """
    number_str = f"{number:08d}"
    payload = {
        FIELD_NUMBER: number_str,
        FIELD_DAY: BIRTH_DAY,
        FIELD_MONTH: BIRTH_MONTH,
        FIELD_YEAR: BIRTH_YEAR,
    }
    if csrf_token:
        payload[CSRF_FIELD_NAME] = csrf_token

    # Choose method
    if FORM_METHOD.upper() == "POST":
        resp = session.post(BASE_URL, data=payload, timeout=30)
    else:
        resp = session.get(BASE_URL, params=payload, timeout=30)

    if DEBUG:
        # Save the response for inspection
        with open(f"debug_{number_str}.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        print(f"\n🔎 Request for {number_str}: status={resp.status_code}")

    resp.raise_for_status()
    found = check_match(resp.text)
    return number, found, resp.text

def worker(numbers, csrf_token, progress_counter, progress_lock):
    """Worker thread: process a chunk of numbers."""
    global found_number   # <-- FIX: declare global at the top of the function

    local_session = requests.Session()
    # Reuse CSRF token (it might be valid for a while)
    for num in numbers:
        # Stop if another thread found the match
        with found_lock:
            if found_number is not None:
                break

        try:
            number, found, response = try_number(num, csrf_token)
            if found:
                with found_lock:
                    if found_number is None:
                        found_number = number
                        # Save result
                        with open("match_result.txt", "w") as f:
                            f.write(f"Number: {number:08d}\n")
                            f.write(f"Birth date: {BIRTH_DAY}/{BIRTH_MONTH}/{BIRTH_YEAR}\n")
                            f.write("\n--- Response snippet (first 2000 chars) ---\n")
                            f.write(response[:2000])
                break

            with progress_lock:
                progress_counter[0] += 1
                if progress_counter[0] % 100 == 0:
                    print(f"⏳ Tried {progress_counter[0]} numbers...", end='\r')
                    sys.stdout.flush()

        except requests.exceptions.RequestException as e:
            print(f"\n⚠️ Network error on {num:08d}: {e}")
            # Wait a bit longer on error, then continue
            time.sleep(DELAY_PER_REQUEST * 2)
        except Exception as e:
            print(f"\n⚠️ Unexpected error on {num:08d}: {e}")

        # Polite delay with jitter
        time.sleep(DELAY_PER_REQUEST + random.uniform(-0.1, 0.1))

def main():
    total = END_NUMBER - START_NUMBER + 1
    print(f"🔍 Searching for birth date: {BIRTH_DAY}/{BIRTH_MONTH}/{BIRTH_YEAR}")
    print(f"📊 Range: {START_NUMBER:08d} – {END_NUMBER:08d} (total {total} numbers)")
    print(f"🧵 Using {MAX_WORKERS} threads, delay ~{DELAY_PER_REQUEST}s each")
    print(f"🐛 Debug mode: {DEBUG}")
    print(f"🌐 Target URL: {BASE_URL}")

    # Fetch CSRF token (if needed)
    csrf_token = get_csrf_token() if CSRF_FIELD_NAME else None
    if CSRF_FIELD_NAME and not csrf_token:
        print("⚠️ CSRF token not found, but proceeding anyway (may fail).")

    # Split numbers into chunks
    numbers = list(range(START_NUMBER, END_NUMBER + 1))
    chunk_size = max(1, len(numbers) // MAX_WORKERS)
    chunks = [numbers[i:i + chunk_size] for i in range(0, len(numbers), chunk_size)]

    progress_counter = [0]
    progress_lock = Lock()

    # Run threads
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(worker, chunk, csrf_token, progress_counter, progress_lock)
            for chunk in chunks
        ]
        for future in as_completed(futures):
            future.result()   # propagate any exception

    # Final output
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
