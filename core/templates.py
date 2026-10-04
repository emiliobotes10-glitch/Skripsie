"""Daily and monthly rainfall templates, for rainfall from any source other
than a SAWS export."""

import datetime
import io

import numpy as np
import pandas as pd

from . import AnalysisError, msg
from .monthly import check_missing_percentage, daily_to_monthly, finish_monthly

SECTION = "template"


def _read_raw(file):
    if isinstance(file, (bytes, bytearray)):
        file = io.BytesIO(file)
    return pd.read_excel(file, header=None)


def find_template_header(raw, exact_names):
    """Find the header row of a template.

    Looks for a row holding every name in exact_names plus a cell starting with
    'rain'. Returns (row position, {name: column position}) or (None, None).
    """
    for row_pos in range(len(raw)):
        cells = [str(c).strip().lower() for c in raw.iloc[row_pos]]
        columns = {}
        for name in exact_names:
            if name in cells:
                columns[name] = cells.index(name)
        for col_pos, cell in enumerate(cells):
            if cell.startswith("rain"):
                columns["rain"] = col_pos
                break
        if len(columns) == len(exact_names) + 1:
            return row_pos, columns
    return None, None


def clean_template_rain(rain_column):
    """Turn a template rainfall column into numbers.

    Returns (values, is_blank, is_flagged):
      blank cell                           -> NaN, is_blank
      negative (-99, -99.9, -9999) or text -> NaN, is_flagged
    """
    is_blank = rain_column.isna() | (rain_column.astype(str).str.strip() == "")
    values = pd.to_numeric(rain_column, errors="coerce")
    is_flagged = (~is_blank) & (values.isna() | (values < 0))
    values = values.where(~is_flagged)
    return values, is_blank, is_flagged


def parse_template_date(cell):
    """Accept a real Excel date, or text written as yyyy-mm-dd or yyyy/mm/dd."""
    if isinstance(cell, (datetime.datetime, datetime.date, pd.Timestamp)):
        return pd.Timestamp(cell).normalize()
    if isinstance(cell, str):
        for date_format in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return pd.Timestamp(datetime.datetime.strptime(cell.strip(), date_format))
            except ValueError:
                continue
    return pd.NaT


# ---------------------------------------------------------------------------
# Daily template
# ---------------------------------------------------------------------------

def read_daily_template(file):
    """Returns (listed_days, messages). listed_days has one row per date in the
    file: index Date, columns Rainfall_mm (NaN if missing), Is_Blank, Is_Flagged."""
    messages = []
    raw = _read_raw(file)
    header_row, columns = find_template_header(raw, ["date"])
    if header_row is None:
        raise AnalysisError("This does not look like the daily template. It needs a 'Date' column and a 'Rainfall_mm' column.")

    data = raw.iloc[header_row + 1:, [columns["date"], columns["rain"]]].copy()
    data.columns = ["Date", "Rainfall_mm"]
    data = data.dropna(how="all")                       # completely empty rows are not data

    data["Date"] = data["Date"].map(parse_template_date)
    skipped_rows = int(data["Date"].isna().sum())
    data = data[data["Date"].notna()]
    if skipped_rows > 0:
        messages.append(msg("warning", f"{skipped_rows} rows had no valid date (yyyy-mm-dd) and were ignored.", SECTION))
    if data.empty:
        raise AnalysisError("No rows with a valid date were found in the file.", messages)

    data["Date"] = pd.to_datetime(data["Date"])
    duplicates = data.loc[data["Date"].duplicated(), "Date"].dt.strftime("%Y-%m-%d").unique()
    if len(duplicates) > 0:
        raise AnalysisError(
            f"These dates appear more than once: {', '.join(duplicates[:10])}. Each date may appear only once.",
            messages,
        )

    data["Rainfall_mm"], data["Is_Blank"], data["Is_Flagged"] = clean_template_rain(data["Rainfall_mm"])
    listed_days = data.sort_values("Date").set_index("Date")

    first_date, last_date = listed_days.index.min(), listed_days.index.max()
    messages.append(msg(
        "info",
        f"Detected: {first_date.strftime('%d %B %Y')} to {last_date.strftime('%d %B %Y')} "
        f"({len(listed_days)} days listed).",
        SECTION,
    ))
    return listed_days, messages


def prepare_daily(file, record_end=None, zero_fill=False, user_lat=None, user_lon=None, listed=None):
    """Everything up to the 12-month totals for the daily template.

    record_end: the last day the record covers (date or 'yyyy-mm-dd');
                defaults to the last date in the file.
    zero_fill:  True if blank or unlisted days had no rain.
    listed:     (listed_days, messages) if the file was already read.
    """
    listed_days, messages = listed if listed is not None else read_daily_template(file)
    messages = list(messages)

    first_date = listed_days.index.min()
    last_date = listed_days.index.max()
    if record_end is None or record_end == "":
        record_end = last_date
    try:
        record_end = pd.Timestamp(record_end)
    except (ValueError, TypeError):
        raise AnalysisError("'My record runs up to' must be a date written as yyyy-mm-dd.", messages)
    if record_end < last_date:
        raise AnalysisError(
            f"'My record runs up to' ({record_end.strftime('%d %B %Y')}) cannot be before the last "
            f"date in the file ({last_date.strftime('%d %B %Y')}).",
            messages,
        )

    # Full calendar from the 1st of the first month to the end of the record.
    # Starting on the 1st lets the WMO rule judge a partial first month.
    # Stopping at the record end lets the incomplete-last-month check work as it does for SAWS.
    calendar = pd.date_range(first_date.replace(day=1), record_end, freq="D")
    rainfall = listed_days["Rainfall_mm"].reindex(calendar)

    if zero_fill:
        flagged_dates = listed_days.index[listed_days["Is_Flagged"]]
        rainfall = rainfall.fillna(0.0)          # blank cells and unlisted days -> no rain
        rainfall.loc[flagged_dates] = np.nan     # days typed as -99 stay missing

    missing_percent = float(rainfall.isna().sum() / len(calendar) * 100)

    try:
        tier, q_msgs = check_missing_percentage(missing_percent)
        messages += q_msgs
        daily_df = pd.DataFrame({"Date": calendar, "Rainfall_mm": rainfall.values})
        monthly, m_msgs = daily_to_monthly(daily_df)
        messages += m_msgs
        monthly, f_msgs = finish_monthly(monthly, tier)
        messages += f_msgs
    except AnalysisError as e:
        raise AnalysisError(str(e), messages + e.messages)

    return _prepared("daily", user_lat, user_lon, record_end, missing_percent, tier, monthly, messages)


# ---------------------------------------------------------------------------
# Monthly template
# ---------------------------------------------------------------------------

def read_monthly_template(file):
    """Returns (listed_months, messages): one row per month in the file, indexed
    by month-end date, with Total_Monthly_Rain (NaN if missing)."""
    messages = []
    raw = _read_raw(file)
    header_row, columns = find_template_header(raw, ["year", "month"])
    if header_row is None:
        raise AnalysisError("This does not look like the monthly template. It needs 'Year', 'Month' and 'Rainfall_mm' columns.")

    data = raw.iloc[header_row + 1:, [columns["year"], columns["month"], columns["rain"]]].copy()
    data.columns = ["Year", "Month", "Total_Monthly_Rain"]
    data = data.dropna(how="all")                       # completely empty rows are not data

    year = pd.to_numeric(data["Year"], errors="coerce")
    month = pd.to_numeric(data["Month"], errors="coerce")
    valid_row = year.between(1800, 2100) & month.between(1, 12) & (year % 1 == 0) & (month % 1 == 0)
    skipped_rows = int((~valid_row).sum())
    data, year, month = data[valid_row].copy(), year[valid_row], month[valid_row]
    if skipped_rows > 0:
        messages.append(msg("warning", f"{skipped_rows} rows had no valid year and month and were ignored.", SECTION))
    if data.empty:
        raise AnalysisError("No rows with a valid year and month were found in the file.", messages)

    data["Month_Date"] = [
        pd.Timestamp(year=int(y), month=int(m), day=1) + pd.offsets.MonthEnd(0)
        for y, m in zip(year, month)
    ]
    duplicates = data.loc[data["Month_Date"].duplicated(), "Month_Date"].dt.strftime("%Y-%m").unique()
    if len(duplicates) > 0:
        raise AnalysisError(
            f"These months appear more than once: {', '.join(duplicates[:10])}. Each month may appear only once.",
            messages,
        )

    data["Total_Monthly_Rain"], _, _ = clean_template_rain(data["Total_Monthly_Rain"])
    listed_months = data.sort_values("Month_Date").set_index("Month_Date")[["Total_Monthly_Rain"]]

    first_month, last_month = listed_months.index.min(), listed_months.index.max()
    messages.append(msg(
        "info",
        f"Detected: {first_month.strftime('%B %Y')} to {last_month.strftime('%B %Y')} "
        f"({len(listed_months)} months listed).",
        SECTION,
    ))
    return listed_months, messages


def prepare_monthly(file, user_lat=None, user_lon=None):
    """Everything up to the 12-month totals for the monthly template."""
    listed_months, messages = read_monthly_template(file)

    # Full list of months; months not in the file become missing
    all_months = pd.date_range(listed_months.index.min(), listed_months.index.max(), freq="ME")
    monthly = listed_months.reindex(all_months)
    monthly.index.name = "Month_Date"

    missing_percent = float(monthly["Total_Monthly_Rain"].isna().sum() / len(all_months) * 100)

    try:
        tier, q_msgs = check_missing_percentage(missing_percent)
        messages += q_msgs
        monthly, f_msgs = finish_monthly(monthly, tier)
        messages += f_msgs
    except AnalysisError as e:
        raise AnalysisError(str(e), messages + e.messages)

    return _prepared("monthly", user_lat, user_lon, all_months[-1], missing_percent, tier, monthly, messages)


def _prepared(path, user_lat, user_lon, analysed_to, missing_percent, tier, monthly, messages):
    # Templates carry no station coordinates, so the location is always the user's.
    lat = 0.0 if user_lat is None else user_lat
    lon = 0.0 if user_lon is None else user_lon
    return {
        "path": path,
        "location": {
            "lat": lat, "lon": lon, "source": "user",
            "file_lat": None, "file_lon": None, "mismatch": False,
        },
        "analysed_to": analysed_to,
        "missing_percent": missing_percent,
        "quality": tier,
        "monthly": monthly,
        "messages": messages,
    }
