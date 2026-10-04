"""The rainfall-upload path. Three file types lead to the same monthly table,
which is then compared with the Smith (2023) thresholds:

  saws     SAWS daily export
  daily    Daily rainfall template
  monthly  Monthly rainfall template
"""

from . import AnalysisError, msg
from .saws import prepare_saws
from .status import classify, deficit_duration
from .templates import prepare_daily, prepare_monthly
from .thresholds import get_saws_thresholds

FILE_TYPES = ("saws", "daily", "monthly")


def prepare_rainfall(file, file_type="saws", user_lat=None, user_lon=None,
                     use_file_coords=True, record_end=None, zero_fill=False):
    """Read the file and build the monthly table with 12-month sums.

    Raises AnalysisError (with .messages) if the file is rejected.
    """
    if file_type == "saws":
        return prepare_saws(file, user_lat, user_lon, use_file_coords)
    if file_type == "daily":
        return prepare_daily(file, record_end, zero_fill, user_lat, user_lon)
    if file_type == "monthly":
        return prepare_monthly(file, user_lat, user_lon)
    raise AnalysisError(f"Unknown file type '{file_type}'. Use one of: {', '.join(FILE_TYPES)}.")


def evaluate_rainfall(prepared, lat=None, lon=None):
    """Thresholds, status and duration (Step 3).

    lat/lon default to the location chosen when the file was prepared.
    """
    if lat is None:
        lat = prepared["location"]["lat"]
    if lon is None:
        lon = prepared["location"]["lon"]
    monthly = prepared["monthly"]
    messages = []

    normal, drought = get_saws_thresholds(lat, lon)
    messages.append(msg(
        "info",
        f"**Normal Threshold (SPI=0):** {normal:.1f} mm | **Drought Threshold (SPI=-1):** {drought:.1f} mm",
        "thresholds",
    ))

    result = {
        "thresholds": {"normal": normal, "drought": drought, "unit": "mm"},
        "latest": None,
        "status": None,
        "severity": None,
        "duration": None,
        "messages": messages,
    }

    valid_idx = monthly["Rolling_12_Month_Rainfall"].last_valid_index()
    if valid_idx is None:
        messages.append(msg("error", "Cannot calculate status: There are no valid 12-month periods in your dataset.", "status"))
        return result

    latest_rainfall = monthly.loc[valid_idx, "Rolling_12_Month_Rainfall"]
    result["latest"] = {"month": valid_idx, "rolling_12": float(latest_rainfall), "spi": None}
    messages.append(msg(
        "write",
        f"**Your most recent 12-month rainfall ({valid_idx.strftime('%B %Y')}):** {latest_rainfall:.1f} mm",
        "status",
    ))

    series = monthly.loc[:valid_idx, "Rolling_12_Month_Rainfall"]
    cls = classify(series, normal, drought, "saws")
    result["status"] = cls["status"]
    messages += cls["messages"]

    if cls["status"] in ("Drought", "Recovering"):
        dur = deficit_duration(series, normal, drought, "saws")
        messages += dur.pop("messages")
        result["duration"] = dur

    return result


def analyse_rainfall(file, file_type="saws", user_lat=None, user_lon=None,
                     use_file_coords=True, record_end=None, zero_fill=False):
    """Single entry point used by the API: prepare + evaluate."""
    prepared = prepare_rainfall(file, file_type, user_lat, user_lon, use_file_coords, record_end, zero_fill)
    try:
        evaluated = evaluate_rainfall(prepared)
    except AnalysisError as e:
        raise AnalysisError(str(e), prepared["messages"] + e.messages)
    result = {**prepared, **evaluated}
    result["messages"] = prepared["messages"] + evaluated["messages"]
    return result
