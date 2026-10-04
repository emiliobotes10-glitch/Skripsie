"""SAWS daily export: read the Excel file, find the station and extraction
date, count missing days and build the daily rainfall table."""

import datetime
import io
import re

import numpy as np
import pandas as pd

from . import AnalysisError, msg
from .monthly import check_missing_percentage, daily_to_monthly, finish_monthly

MISSING_FLAGS = ["***", "----", "A", "B", "---", "="]
MONTH_COLUMNS = [(m, f"Unnamed: {m}") for m in range(1, 13)]


# ---------------------------------------------------------------------------
# Reading the file
# ---------------------------------------------------------------------------

def read_saws_excel(file):
    """file: bytes, a path, a file-like object (e.g. Streamlit upload), or an
    already-read DataFrame."""
    if isinstance(file, pd.DataFrame):
        return file
    if isinstance(file, (bytes, bytearray)):
        file = io.BytesIO(file)
    return pd.read_excel(file)


def read_station_info(rain_data):
    """Return (file_lat, file_lon, cutoff_date) from the SAWS header rows.

    Any of them may be None if the file has no SAWS-style header.
    The cut-off is the latest 'Extracted YYYY/MM/DD' date: days after it had not
    happened yet when the file was extracted.
    """
    file_lat, file_lon = None, None
    cutoff_date = None
    if "Unnamed: 0" not in rain_data.columns:
        return file_lat, file_lon, cutoff_date

    # str() on each value (not .astype(str)): with pandas 3, astype(str) keeps
    # empty cells as NaN, which made the original script crash.
    first_col = [str(v) for v in rain_data["Unnamed: 0"]]

    for value in first_col:
        if "Daily Rain (mm) Data for station" in value:
            matches = re.findall(r"-?\d+\.\d+", value)
            if len(matches) >= 2:
                file_lat, file_lon = float(matches[0]), float(matches[1])
                break

    if file_lat is not None and file_lat > 0:
        file_lat = -file_lat

    for value in first_col:
        if "Daily Rain" in value:
            match = re.search(r"Extracted\s+(\d{4})/(\d{1,2})/(\d{1,2})", value)
            if match:
                try:
                    header_date = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                except ValueError:
                    continue
                if cutoff_date is None or header_date > cutoff_date:
                    cutoff_date = header_date

    return file_lat, file_lon, cutoff_date


def location_mismatch(user_lat, user_lon, file_lat, file_lon):
    """True if the user gave a location that is >0.1 degrees from the station."""
    if file_lat is None or user_lat is None or user_lon is None:
        return False
    if user_lat == 0.0 and user_lon == 0.0:
        return False
    return abs(user_lat - file_lat) > 0.1 or abs(user_lon - file_lon) > 0.1


def resolve_location(user_lat, user_lon, file_lat, file_lon, use_file_coords=True):
    """Decide which coordinates to use. Returns (lat, lon, source, messages).

    user_lat/user_lon may be None (or 0.0, 0.0) when the user gave no location.
    """
    messages = []
    if user_lat is None or user_lon is None:
        user_lat, user_lon = 0.0, 0.0
    lat, lon, source = user_lat, user_lon, "user"

    if file_lat is not None:
        if user_lat == 0.0 and user_lon == 0.0:
            lat, lon, source = file_lat, file_lon, "file"
            messages.append(msg("info", f"Using station location from file: {file_lat}, {file_lon}", "location"))
        elif location_mismatch(user_lat, user_lon, file_lat, file_lon):
            messages.append(msg(
                "warning",
                f"Your location ({user_lat:.4f}, {user_lon:.4f}) doesn't match "
                f"the station in the file ({file_lat}, {file_lon}). "
                f"Thresholds will be taken from the location you use.",
                "location",
            ))
            if use_file_coords:
                lat, lon, source = file_lat, file_lon, "file"
        else:
            messages.append(msg("success", "Your location matches the station in the file.", "location"))

    return lat, lon, source, messages


# ---------------------------------------------------------------------------
# Walking the day/month grid
# ---------------------------------------------------------------------------

def _iter_cells(rain_data, cutoff_date):
    """Yield (date, raw cell value) for every real calendar day in the file,
    up to the cut-off date."""
    current_year = 0
    for _, row in rain_data.iterrows():
        first_col_value = str(row.get("Unnamed: 0", ""))

        if "Daily Rain" in first_col_value:
            words = first_col_value.split()
            for i, word in enumerate(words):
                if word.isdigit() and len(word) == 4:
                    if (i + 1) < len(words) and words[i + 1] == "m":
                        continue
                    current_year = int(word)
                    break

        if first_col_value.isdigit() and 1 <= int(first_col_value) <= 31:
            current_day = int(first_col_value)
            for current_month, column_name in MONTH_COLUMNS:
                if column_name not in row:
                    continue
                try:
                    actual_date = datetime.date(current_year, current_month, current_day)
                except ValueError:
                    continue
                if cutoff_date is not None and actual_date > cutoff_date:
                    continue
                yield actual_date, row[column_name]


def missing_percentage(rain_data, cutoff_date):
    """Percentage of calendar days (up to the cut-off) flagged as missing.

    Raises AnalysisError if no calendar days were found.
    """
    cell_count = 0
    value_count = 0
    for _, cell_data in _iter_cells(rain_data, cutoff_date):
        cell_count += 1
        if pd.isna(cell_data) or str(cell_data).strip() == "":
            value_count += 1
        else:
            text_data = str(cell_data).strip()
            if text_data in MISSING_FLAGS:
                pass
            elif "C" in text_data or "E" in text_data:
                value_count += 1
            else:
                try:
                    float(text_data)
                    value_count += 1
                except ValueError:
                    pass

    if cell_count == 0:
        raise AnalysisError("Error: 0 valid calendar days were processed. Check file formatting.")
    return (cell_count - value_count) / cell_count * 100


def _parse_value(cell_data):
    if pd.isna(cell_data) or str(cell_data).strip() == "":
        return 0.0
    text_data = str(cell_data).strip()
    if text_data in MISSING_FLAGS:
        return np.nan
    if "C" in text_data:
        text_data = text_data.replace("C", "")
    elif "E" in text_data:
        text_data = text_data.replace("E", "")
    try:
        return float(text_data)
    except ValueError:
        return 0.0


def clean_daily(rain_data, cutoff_date):
    """Daily DataFrame with columns Date, Rainfall_mm (NaN = flagged missing)."""
    dates, values = [], []
    for actual_date, cell_data in _iter_cells(rain_data, cutoff_date):
        dates.append(actual_date)
        values.append(_parse_value(cell_data))
    return pd.DataFrame({"Date": pd.to_datetime(dates), "Rainfall_mm": values})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def prepare_saws(file, user_lat=None, user_lon=None, use_file_coords=True):
    """Everything up to the 12-month totals for a SAWS daily export.

    Raises AnalysisError (with .messages) if the file is rejected.
    """
    messages = []
    rain_data = read_saws_excel(file)

    file_lat, file_lon, cutoff_date = read_station_info(rain_data)
    mismatch = location_mismatch(user_lat, user_lon, file_lat, file_lon)
    lat, lon, source, loc_msgs = resolve_location(user_lat, user_lon, file_lat, file_lon, use_file_coords)
    messages += loc_msgs

    if cutoff_date is not None:
        messages.append(msg("info", f"Data analysed up to {cutoff_date.strftime('%d %B %Y')} (SAWS extraction date).", "quality"))
    else:
        messages.append(msg("info", "No extraction date found in file. Analysing to the end of the file.", "quality"))

    try:
        missing_percent = missing_percentage(rain_data, cutoff_date)
        tier, q_msgs = check_missing_percentage(missing_percent)
        messages += q_msgs

        daily_df = clean_daily(rain_data, cutoff_date)
        monthly, m_msgs = daily_to_monthly(daily_df)
        messages += m_msgs
        monthly, f_msgs = finish_monthly(monthly, tier)
        messages += f_msgs
    except AnalysisError as e:
        raise AnalysisError(str(e), messages + e.messages)

    return {
        "path": "saws",
        "location": {
            "lat": lat, "lon": lon, "source": source,
            "file_lat": file_lat, "file_lon": file_lon, "mismatch": mismatch,
        },
        "analysed_to": cutoff_date,
        "missing_percent": missing_percent,
        "quality": tier,
        "monthly": monthly,
        "messages": messages,
    }
