import streamlit as st
import pandas as pd
import numpy as np
import xarray as xr
import scipy.stats as stats
import spei

# ==========================================
# PHASE 1: APP SETUP & USER INTERFACE
# ==========================================
st.set_page_config(page_title="CHIRPS Drought Tracker", layout="centered")
st.title("CHIRPS Drought Tracker")

st.markdown("### ⚠️ Notice: This application uses CHIRPS satellite rainfall data to calculate SPI-12 at any location in South Africa.")
st.markdown("No rainfall file upload is needed. Just enter your coordinates.")

st.markdown("#### Enter your location")
col1, col2 = st.columns(2)
with col1:
    user_lat = st.number_input("Latitude (e.g., -33.7609)", value=-33.7609, format="%.4f")
with col2:
    user_lon = st.number_input("Longitude (e.g., 19.4741)", value=19.4741, format="%.4f")

# ==========================================
# PHASE 2: EXTRACT CHIRPS DATA FROM NETCDF
# ==========================================
if st.button("Run SPI Calculation", type="primary"):

    # Basic coordinate check for South Africa bounds
    if not (-35.0 <= user_lat <= -22.0 and 16.0 <= user_lon <= 33.0):
        st.error("❌ Coordinates are outside South Africa. Please check your latitude and longitude.")
        st.stop()

    st.info("Loading CHIRPS satellite data for your location...")

    try:
        ds = xr.open_dataset("chirps_sa_monthly.nc")
    except FileNotFoundError:
        st.error("❌ Could not find 'chirps_sa_monthly.nc'. Make sure the file is in the same folder as this app.")
        st.stop()

    # Extract the monthly rainfall time series at the nearest grid cell
    point_data = ds["rainfall"].sel(
        latitude=user_lat,
        longitude=user_lon,
        method="nearest"
    )

    # Convert to a pandas DataFrame
    monthly_df = point_data.to_dataframe().reset_index()
    monthly_df = monthly_df.rename(columns={"time": "Month_Date", "rainfall": "Monthly_Rain"})
    monthly_df = monthly_df[["Month_Date", "Monthly_Rain"]].copy()
    monthly_df = monthly_df.set_index("Month_Date")
    monthly_df = monthly_df.sort_index()

    ds.close()

    # Check we actually got data (not all NaN, which would mean the coordinate fell outside the clipped area)
    if monthly_df["Monthly_Rain"].dropna().empty:
        st.error("❌ No rainfall data found at this location. The coordinate may be outside the CHIRPS land coverage.")
        st.stop()

    st.success(f"✅ Extracted {len(monthly_df.dropna())} months of CHIRPS data.")

    # ==========================================
    # PHASE 3: 12-MONTH ROLLING SUM
    # ==========================================
    st.info("Calculating 12-month rolling rainfall sum...")

    timescale = 12
    monthly_df["Rolling_12_Month_Rainfall"] = monthly_df["Monthly_Rain"].rolling(
        window=timescale, min_periods=timescale
    ).sum()

    # ==========================================
    # PHASE 4: SPI CALCULATION
    # ==========================================
    st.info("Fitting Gamma distribution and calculating SPI-12...")

    spi_values = spei.spi(monthly_df["Rolling_12_Month_Rainfall"], dist=stats.gamma)
    monthly_df["SPI_12"] = spi_values

    # ==========================================
    # DISPLAY RESULTS
    # ==========================================
    st.markdown("### 📊 CHIRPS SPI-12 Results")

    # Show the last 24 months for a quick overview
    display_df = monthly_df.dropna().tail(24)
    st.dataframe(display_df)

    # Show the most recent SPI value
    latest_valid = monthly_df["SPI_12"].dropna()
    if not latest_valid.empty:
        latest_spi = latest_valid.iloc[-1]
        latest_date = latest_valid.index[-1].strftime("%B %Y")
        latest_rainfall = monthly_df.loc[latest_valid.index[-1], "Rolling_12_Month_Rainfall"]

        st.markdown("---")
        st.markdown(f"**Most recent month:** {latest_date}")
        st.markdown(f"**12-month cumulative rainfall:** {latest_rainfall:.1f} mm")
        st.markdown(f"**SPI-12 value:** {latest_spi:.2f}")

        if latest_spi >= 0:
            st.success("✅ No drought. Rainfall is at or above normal.")
        elif latest_spi > -1:
            st.warning("⚠️ Below normal rainfall, but not yet at drought level (SPI between -1 and 0).")
        elif latest_spi > -1.5:
            st.error("🚨 Moderate drought (SPI between -1 and -1.5).")
        elif latest_spi > -2:
            st.error("🚨 Severe drought (SPI between -1.5 and -2).")
        else:
            st.error("🚨 Extreme drought (SPI below -2).")
    else:
        st.error("❌ Could not calculate SPI. Insufficient valid data.")
