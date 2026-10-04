"""CHIRPS satellite path: extract one grid cell, compute 12-month sums,
SPI-12 and the averaged precipitation thresholds."""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.stats as stats
import xarray as xr

from . import AnalysisError, in_south_africa, msg
from .status import classify, deficit_duration

CHIRPS_NC = Path(__file__).resolve().parent.parent / "chirps_sa_monthly.nc"
CHIRPS_RECENT_NC = Path(__file__).resolve().parent.parent / "chirps_sa_recent.nc"
TIMESCALE = 12
NORMAL_SPI = 0
DROUGHT_SPI = -1


def load_cell(lat, lon, nc_path=CHIRPS_NC, recent_path=CHIRPS_RECENT_NC):
    """Monthly rainfall at the nearest CHIRPS cell, indexed by Month_Date.

    Reads the history file and, if it exists, the recent file (months added by
    update_chirps.py), and joins them by date. Only this location's values are
    read from each file, so whole maps are never loaded into memory (important
    on a 512 MB server).
    """
    try:
        ds = xr.open_dataset(nc_path)
    except FileNotFoundError:
        raise AnalysisError("CHIRPS data file not found.")
    try:
        point = ds["rainfall"].sel(latitude=lat, longitude=lon, method="nearest").load()
    finally:
        ds.close()

    if os.path.exists(recent_path):
        recent = xr.open_dataset(recent_path)
        try:
            recent_point = recent["rainfall"].sel(latitude=lat, longitude=lon, method="nearest").load()
        finally:
            recent.close()
        point = xr.concat([point, recent_point], dim="time")

    df = point.to_dataframe().reset_index()
    df = df.rename(columns={"time": "Month_Date", "rainfall": "Monthly_Rain"})
    df = df[["Month_Date", "Monthly_Rain"]].copy()
    df["Month_Date"] = pd.to_datetime(df["Month_Date"])
    return df.set_index("Month_Date").sort_index()


def compute_spi(monthly_df):
    """Add Rolling_12_Month_Rainfall and SPI_12 columns.

    Returns (monthly_df, threshold_normal, threshold_drought) where the
    thresholds are the mm amounts for SPI = 0 and SPI = -1, averaged over the
    12 calendar months.
    """
    monthly_df["Rolling_12_Month_Rainfall"] = monthly_df["Monthly_Rain"].rolling(
        window=TIMESCALE, min_periods=TIMESCALE
    ).sum()
    monthly_df["SPI_12"] = np.nan
    spi_0_thresholds, spi_minus_1_thresholds = [], []

    for month in range(1, 13):
        month_data = monthly_df[monthly_df.index.month == month]["Rolling_12_Month_Rainfall"].dropna()
        if month_data.empty:
            continue

        # Mixed distribution H(x) = q + (1 - q) * G(x): q is the probability of
        # zero rainfall, G a gamma fitted to the non-zero 12-month totals.
        q = (month_data == 0).sum() / len(month_data)
        month_positive = month_data[month_data > 0]
        if month_positive.empty:
            continue

        shape, _, scale = stats.gamma.fit(month_positive, floc=0)

        H = q + (1 - q) * stats.gamma.cdf(month_data, shape, loc=0, scale=scale)
        monthly_df.loc[month_data.index, "SPI_12"] = stats.norm.ppf(H)

        # Invert the distribution: rainfall at SPI = 0 and SPI = -1
        month_thresholds = []
        for target_p in [stats.norm.cdf(0), stats.norm.cdf(-1)]:
            if target_p <= q:
                threshold = 0.0
            else:
                threshold = stats.gamma.ppf((target_p - q) / (1 - q), shape, loc=0, scale=scale)
            month_thresholds.append(threshold)

        spi_0_thresholds.append(month_thresholds[0])
        spi_minus_1_thresholds.append(month_thresholds[1])

    if spi_0_thresholds and spi_minus_1_thresholds:
        return monthly_df, float(np.mean(spi_0_thresholds)), float(np.mean(spi_minus_1_thresholds))
    return monthly_df, 0.0, 0.0


def analyse_chirps(lat, lon, nc_path=CHIRPS_NC, recent_path=CHIRPS_RECENT_NC):
    if lat is None or lon is None or not in_south_africa(lat, lon):
        raise AnalysisError("Coordinates are outside South Africa. Please check your latitude and longitude.")

    monthly_df = load_cell(lat, lon, nc_path, recent_path)
    if monthly_df["Monthly_Rain"].dropna().empty:
        raise AnalysisError(
            "No rainfall data found at this location. "
            "The coordinate may be outside the CHIRPS land coverage."
        )

    messages = [msg("success", f"Extracted {len(monthly_df.dropna())} months of CHIRPS data.", "data")]

    monthly_df, normal_mm, drought_mm = compute_spi(monthly_df)
    messages.append(msg("info", "**CHIRPS Precipitation Thresholds (Smith Method - Averaged over 12 months):**", "thresholds"))
    messages.append(msg("write", f"Normal (SPI=0): **{normal_mm:.1f} mm** | Drought (SPI=-1): **{drought_mm:.1f} mm**", "thresholds"))

    result = {
        "path": "chirps",
        "location": {"lat": lat, "lon": lon, "source": "user"},
        "analysed_to": None,
        "missing_percent": None,
        "thresholds": {"normal": normal_mm, "drought": drought_mm, "unit": "mm"},
        "latest": None,
        "status": None,
        "severity": None,
        "duration": None,
        "monthly": monthly_df,
        "messages": messages,
    }

    valid_idx = monthly_df["SPI_12"].last_valid_index()
    if valid_idx is None:
        messages.append(msg("error", "Could not calculate SPI. Insufficient valid data.", "status"))
        return result

    latest_spi = float(monthly_df.loc[valid_idx, "SPI_12"])
    latest_rainfall = float(monthly_df.loc[valid_idx, "Rolling_12_Month_Rainfall"])

    messages.append(msg("markdown", f"**Most recent month:** {valid_idx.strftime('%B %Y')}", "status"))
    messages.append(msg("markdown", f"**12-month cumulative rainfall:** {latest_rainfall:.1f} mm", "status"))
    messages.append(msg("markdown", f"**SPI-12 value:** {latest_spi:.2f}", "status"))

    series = monthly_df.loc[:valid_idx, "SPI_12"]
    cls = classify(series, NORMAL_SPI, DROUGHT_SPI, "chirps")
    messages += cls["messages"]

    duration = None
    if cls["status"] in ("Drought", "Recovering"):
        duration = deficit_duration(series, NORMAL_SPI, DROUGHT_SPI, "chirps", pre_gap_drought_inclusive=True)
        messages += duration.pop("messages")

    result.update({
        "analysed_to": valid_idx,
        "latest": {"month": valid_idx, "rolling_12": latest_rainfall, "spi": latest_spi},
        "status": cls["status"],
        "severity": cls["severity"],
        "duration": duration,
    })
    return result
