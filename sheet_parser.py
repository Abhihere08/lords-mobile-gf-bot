"""
Google Sheets Parser for Lords Mobile Guild Fest (GF) Loot Schedule.
Fetches and parses live data for both [B|M] Blood Mafia and [b|M] Little Blood Mafia.
"""

import re
import csv
import io
import time
import datetime
from typing import Dict, List, Optional, Tuple, Any
import requests
import pytz

# Known month abbreviations mapping
MONTH_MAP = {
    "JAN": 1, "JANUARY": 1,
    "FEB": 2, "FEBRUARY": 2,
    "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "MAY": 5,
    "JUN": 6, "JUNE": 6,
    "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEP": 9, "SEPT": 9, "SEPTEMBER": 9,
    "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12
}

PLACEHOLDER_NAMES = {"x", "none", "empty", "open", "n/a", "na", "-", ""}


def normalize_sheet_url(url: str) -> str:
    """
    Converts any Google Sheet URL (edit, export) into the live GViz CSV endpoint
    and always reads the LEFTMOST (first) tab by position (ignoring any gid in the URL).

    This lets the bot auto-follow the active Guild Fest tab: place the current GF
    roster as the left-most tab each cycle; locked/hidden old-GF tabs on the right
    are ignored, so config.json never needs its sheet_url/gid edited between cycles.

    Google Visualization API queries the live in-memory spreadsheet engine directly,
    eliminating the 2-5 minute Google Drive export delay.
    """
    match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
    if match:
        sheet_id = match.group(1)
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv"
    return url


def fetch_sheet_csv(csv_url: str) -> str:
    """
    Fetches the latest CSV content from Google Sheets.
    Appends a microsecond timestamp cache-buster and no-cache headers to guarantee 100% live data.
    """
    live_url = normalize_sheet_url(csv_url)
    cache_buster = f"_t={int(time.time() * 1000)}"
    sep = "&" if "?" in live_url else "?"
    fresh_url = f"{live_url}{sep}{cache_buster}"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0"
    }
    response = requests.get(fresh_url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.text


def parse_gf_date_from_text(text: str, reference_year: Optional[int] = None) -> Optional[datetime.date]:
    """
    Parses dates like 'SEPT 6 - 13', 'OCT 4 - 11', 'SEPT 7', '2026-09-06', etc.
    Returns datetime.date.
    """
    if not reference_year:
        reference_year = datetime.datetime.now().year

    # 1. Look for ISO date YYYY-MM-DD
    iso_match = re.search(r'\b(20\d\d)[-/](\d{1,2})[-/](\d{1,2})\b', text)
    if iso_match:
        y, m, d = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
        return datetime.date(y, m, d)

    # 2. Look for Month Name + Day Range e.g. "SEPT 6 - 13" or "SEPTEMBER 6"
    pattern = r'\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|SEPT|OCT|NOV|DEC)[A-Z]*\s*(\d{1,2})(?:\s*[-–—to]+\s*(\d{1,2}))?\b'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        month_str = match.group(1).upper()
        month_num = MONTH_MAP.get(month_str, 9)
        day_num = int(match.group(2))
        return datetime.date(reference_year, month_num, day_num)

    return None


def extract_header_date(csv_rows: List[List[str]]) -> Optional[datetime.date]:
    """Scans the top 10 rows for the GF event date string."""
    for row in csv_rows[:10]:
        combined_text = " ".join(row)
        parsed_date = parse_gf_date_from_text(combined_text)
        if parsed_date:
            return parsed_date
    return None


def clean_member_name(raw_name: str) -> Optional[str]:
    """Cleans up a player name and filters out placeholders."""
    if not raw_name:
        return None
    cleaned = raw_name.strip()
    cleaned = cleaned.strip("`'\"")
    if cleaned.lower() in PLACEHOLDER_NAMES:
        return None
    return cleaned if len(cleaned) > 0 else None


def parse_sheet_time(raw: str) -> Optional[Tuple[int, int]]:
    """
    Parses a time value from sheet columns L/M (e.g., '2100', '500', '05:00', '21:00').
    Returns (hour, minute) in 24-hour format, or None if unparseable.
    """
    if not raw:
        return None
    s = raw.strip().replace(":", "").replace(" ", "")
    if not s:
        return None
    # Handle formats like "2100", "0500", "500", "0300"
    if s.isdigit():
        if len(s) <= 2:
            # e.g., "5" or "21" -> hour only
            h = int(s)
            return (h, 0) if 0 <= h <= 23 else None
        elif len(s) == 3:
            # e.g., "500" -> 5:00
            h = int(s[0])
            m = int(s[1:])
            return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None
        elif len(s) == 4:
            # e.g., "2100" -> 21:00, "0500" -> 5:00
            h = int(s[:2])
            m = int(s[2:])
            return (h, m) if 0 <= h <= 23 and 0 <= m <= 59 else None
    return None


def parse_roster_table(csv_rows: List[List[str]]) -> Dict[str, Any]:
    """
    Parses both [B|M] Blood Mafia and [b|M] Little Blood Mafia tables.
    Uses resilient slot detection: locates Slot 0 in each table.
    Note: L/M column times are parsed but NOT used for slot timing (fixed 05:00 UTC reset).
    """
    bm_slots: Dict[int, List[str]] = {}
    little_bm_slots: Dict[int, List[str]] = {}

    # Find Slot 0 locations in the sheet
    slot_0_locations = []
    for r_idx, row in enumerate(csv_rows):
        for c_idx, cell in enumerate(row):
            if cell.strip() == "0":
                row_str = " ".join(row)
                if "2200" in row_str or "2100" in row_str or "Day" in row_str or "Sun" in row_str:
                    slot_0_locations.append((r_idx, c_idx))

    # Fallback to header search if slot_0_locations is empty
    if not slot_0_locations:
        for r_idx, row in enumerate(csv_rows):
            for c_idx, cell in enumerate(row):
                if "Time Slot" in cell or "Slot" in cell:
                    slot_0_locations.append((r_idx + 1, c_idx))

    for table_idx, (r0, c_idx) in enumerate(slot_0_locations):
        target_dict = bm_slots if table_idx == 0 else little_bm_slots
        member_col_indices = [c_idx + 4, c_idx + 5, c_idx + 6, c_idx + 7]
        next_r = slot_0_locations[table_idx + 1][0] if table_idx + 1 < len(slot_0_locations) else len(csv_rows)

        for r in range(r0, next_r):
            row = csv_rows[r]
            if len(row) <= c_idx:
                continue
            cell_val = row[c_idx].strip()
            if not cell_val.isdigit():
                continue
            slot_num = int(cell_val)
            if slot_num < 0:
                continue

            members = []
            for mc in member_col_indices:
                if mc < len(row):
                    cleaned = clean_member_name(row[mc])
                    if cleaned:
                        members.append(cleaned)

            target_dict[slot_num] = members

    return {
        "BM": bm_slots,
        "bM": little_bm_slots,
    }


def parse_google_sheet(csv_url: str) -> Dict[str, Any]:
    """
    Full pipeline: fetches Google Sheet CSV via live GViz endpoint,
    extracts start date, and returns parsed slots for both guilds.
    """
    csv_text = fetch_sheet_csv(csv_url)
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)

    header_date = extract_header_date(rows)
    parsed = parse_roster_table(rows)

    return {
        "header_date": header_date,
        "rosters": {"BM": parsed["BM"], "bM": parsed["bM"]},
        "raw_row_count": len(rows)
    }


if __name__ == "__main__":
    test_url = "https://docs.google.com/spreadsheets/d/16mnYiVH-OtAewbMIlWnmL-7p63PzzS_yphg-w6Z12F8/edit?gid=0#gid=0"
    print("Testing live parser with resilient slot finder...")
    result = parse_google_sheet(test_url)
    print(f"Detected Event Start Date: {result['header_date']}")
    print("\n--- [B|M] Blood Mafia Slots ---")
    for slot, members in result['rosters']['BM'].items():
        if members:
            print(f"Slot {slot:02d}: {', '.join(members)} ({len(members)}/4)")
    print("\n--- [b|M] Little Blood Mafia Slots ---")
    for slot, members in result['rosters']['bM'].items():
        if members:
            print(f"Slot {slot:02d}: {', '.join(members)} ({len(members)}/4)")
