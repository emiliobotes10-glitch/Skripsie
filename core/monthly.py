"""Steps shared by every rainfall file type: the missing-data rule, turning
daily rainfall into monthly totals, and the 12-month rolling sums."""

import numpy as np
import pandas as pd

from . import AnalysisError, msg

TIMESCALE = 12


def check_missing_percentage(percentage_missing):
    """Shared data-quality rule. Returns (tier, messages); tier: good | warning.

    Raises AnalysisError when more than 15% is missing.
    """
    messages = [msg("write", f"**Data Quality Scan:** {percentage_missing:.2f}% of data is marked as missing.", "quality")]

    if percentage_missing > 15.0:
        raise AnalysisError(
            f"Data rejected. Your percentage of missing data ({percentage_missing:.2f}%) is > 15%. "
            "Cannot yield accurate results.",
            messages,
        )
    if 10.0 <= percentage_missing <= 15.0:
        messages.append(msg("warning", "Warning: Missing data is between 10-15%. Proceeding, but results may be less reliable.", "quality"))
        return "warning", messages

    messages.append(msg("success", "Data quality is good (< 10% missing).", "quality"))
    return "good", messages


def apply_monthly_data_rule(monthly_series):
    """WMO-based rule: a month with >= 11 missing days or >= 5 consecutive
    missing days is NaN; otherwise missing days are filled pro rata."""
    total_days = len(monthly_series)
    valid_days = monthly_series.notna().sum()
    missing_days = total_days - valid_days

    max_consecutive_missing = 0
    current_streak = 0
    for value in monthly_series:
        if pd.isna(value):
            current_streak += 1
            max_consecutive_missing = max(max_consecutive_missing, current_streak)
        else:
            current_streak = 0

    if missing_days >= 11 or max_consecutive_missing >= 5:
        return np.nan
    if missing_days > 0:
        return monthly_series.sum() * (total_days / valid_days)
    return monthly_series.sum()


def daily_to_monthly(daily_df):
    """Daily table (Date, Rainfall_mm) -> monthly table indexed by Month_Date
    with Total_Monthly_Rain. Returns (table, messages)."""
    messages = []
    monthly_stats = (
        daily_df
        .groupby(pd.Grouper(key="Date", freq="ME"))["Rainfall_mm"]
        .apply(apply_monthly_data_rule)
        .reset_index(name="Total_Monthly_Rain")
        .rename(columns={"Date": "Month_Date"})
    )

    # Drop the latest month if the data stops before the month ends.
    # Missing days inside a finished month are left to the WMO rule.
    if not monthly_stats.empty:
        latest_month = monthly_stats["Month_Date"].iloc[-1]
        days_in_latest_month = latest_month.days_in_month
        days_present_latest = len(daily_df[
            (daily_df["Date"].dt.year == latest_month.year)
            & (daily_df["Date"].dt.month == latest_month.month)
        ])
        if days_present_latest < days_in_latest_month:
            messages.append(msg(
                "warning",
                f"**Data Adjusted:** The current month ({latest_month.strftime('%B %Y')}) "
                f"is incomplete ({int(days_present_latest)}/{int(days_in_latest_month)} "
                f"days in file). It has been excluded from the analysis.",
                "monthly",
            ))
            monthly_stats = monthly_stats[monthly_stats["Month_Date"] != latest_month]

    return monthly_stats.set_index("Month_Date"), messages


def finish_monthly(monthly_stats, tier):
    """Check there are at least 12 months, add Rolling_12_Month_Rainfall and
    the 10-15% reminder. Returns (table, messages)."""
    total_months = len(monthly_stats)
    if total_months < 12:
        raise AnalysisError(
            f"Insufficient data. You only have {total_months} months of data. Exactly 12 months minimum required."
        )

    monthly_stats = monthly_stats.copy()
    monthly_stats["Rolling_12_Month_Rainfall"] = (
        monthly_stats["Total_Monthly_Rain"].rolling(window=TIMESCALE, min_periods=TIMESCALE).sum()
    )

    messages = []
    if tier == "warning":
        messages.append(msg(
            "warning",
            "**Reminder:** Due to the missing data percentage (10-15%) in your upload, "
            "this final cumulative sum may be slightly underestimated.",
            "reminder",
        ))
    return monthly_stats, messages
