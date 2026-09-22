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
    
    # Ensure the index is a datetime object so we can group by month later
    monthly_df["Month_Date"] = pd.to_datetime(monthly_df["Month_Date"])
    monthly_df = monthly_df.set_index("Month_Date")
    monthly_df = monthly_df.sort_index()

    ds.close()

    # Check we actually got data
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
    # PHASE 4: SPI CALCULATION & THRESHOLD EXTRACTION
    # ==========================================
    st.info("Fitting distributions per calendar month and calculating SPI-12...")

    # The SPEI library automatically handles the per-month fitting for the forward SPI calculation
    spi_values = spei.spi(monthly_df["Rolling_12_Month_Rainfall"], dist=stats.gamma)
    monthly_df["SPI_12"] = spi_values

    # --- Extract Precipitation Thresholds from the Fitted Gamma (Smith Methodology) ---
    spi_0_thresholds = []
    spi_minus_1_thresholds = []

    # Iterate through all 12 calendar months (1 = Jan, 12 = Dec)
    for month in range(1, 13):
        # Isolate the rolling sums that end in this specific calendar month
        month_data = monthly_df[monthly_df.index.month == month]["Rolling_12_Month_Rainfall"].dropna()
        
        if month_data.empty:
            continue
            
        n_total = len(month_data)
        
        # Gamma distribution is only defined for x > 0
        month_positive = month_data[month_data > 0]
        n_zeros = n_total - len(month_positive)
        
        # q is the empirical probability of zero rainfall for this calendar month
        q = n_zeros / n_total
        
        if not month_positive.empty:
            # Fit gamma for the non-zero values of this specific month
            shape, loc, scale = stats.gamma.fit(month_positive, floc=0)
            
            # Helper function to invert the McKee H(x) mixed distribution
            def get_rainfall_for_prob(target_p):
                # If target probability is less than or equal to the probability of zero rain, threshold is 0
                if target_p <= q:
                    return 0.0
                else:
                    # Adjust probability to account for zeros before querying the Gamma inverse CDF
                    adjusted_p = (target_p - q) / (1.0 - q)
                    return stats.gamma.ppf(adjusted_p, shape, loc, scale)
            
            # Find the mm rainfall corresponding to SPI=0 (P=0.500) and SPI=-1 (P=0.1587)
            thresh_0 = get_rainfall_for_prob(0.500)
            thresh_minus_1 = get_rainfall_for_prob(0.1587)
            
            spi_0_thresholds.append(thresh_0)
            spi_minus_1_thresholds.append(thresh_minus_1)

    # Average the 12 monthly thresholds to get a single station threshold (Smith method)
    if spi_0_thresholds and spi_minus_1_thresholds:
        threshold_normal = np.mean(spi_0_thresholds)
        threshold_drought = np.mean(spi_minus_1_thresholds)
    else:
        threshold_normal = 0
        threshold_drought = 0

    st.info(f"📍 **Station Precipitation Thresholds (Smith Method - Averaged over 12 months):**")
    st.write(f"Normal (SPI=0): **{threshold_normal:.1f} mm** | Drought (SPI=-1): **{threshold_drought:.1f} mm**")

    # ==========================================
    # DISPLAY RESULTS
    # ==========================================
    st.markdown("### 📊 CHIRPS SPI-12 Results (Last 24 Months)")

    display_df = monthly_df.dropna().tail(24)
    st.dataframe(display_df)

    # --- Download Button for Full Dataset ---
    csv_data = monthly_df.to_csv()
    st.download_button(
        label="📥 Download Full SPI-12 Results (CSV)",
        data=csv_data,
        file_name="CHIRPS_SPI12_Results.csv",
        mime="text/csv"
    )

    # ==========================================
    # PHASE 5: DROUGHT STATUS & GREY ZONE LOGIC
    # ==========================================
    st.markdown("---")
    st.markdown("### Step 2: Drought Status")

    latest_valid = monthly_df["SPI_12"].dropna()

    if latest_valid.empty:
        st.error("❌ Could not calculate SPI. Insufficient valid data.")
        st.stop()

    latest_spi = latest_valid.iloc[-1]
    latest_date = latest_valid.index[-1].strftime("%B %Y")
    latest_rainfall = monthly_df.loc[latest_valid.index[-1], "Rolling_12_Month_Rainfall"]

    st.markdown(f"**Most recent month:** {latest_date}")
    st.markdown(f"**12-month cumulative rainfall:** {latest_rainfall:.1f} mm")
    st.markdown(f"**SPI-12 value:** {latest_spi:.2f}")

    # --- Chart: Rolling Rainfall vs Precipitation Thresholds (in mm) ---
    st.markdown("#### 📈 Historical 12-Month Rainfall vs. Averaged Thresholds")
    chart_data = monthly_df[["Rolling_12_Month_Rainfall"]].dropna().copy()
    chart_data["Normal (SPI=0 Average)"] = threshold_normal
    chart_data["Drought (SPI=-1 Average)"] = threshold_drought
    st.line_chart(chart_data)

    # --- Chart: Historical SPI with threshold lines ---
    st.markdown("#### 📈 Historical SPI-12")
    spi_chart = monthly_df[["SPI_12"]].dropna().copy()
    spi_chart["SPI = 0 (Normal)"] = 0.0
    spi_chart["SPI = -1 (Drought)"] = -1.0
    st.line_chart(spi_chart)

    # --- Determine Status ---
    status = ""

    # Category A: Clearly Safe
    if latest_spi >= 0:
        st.success("✅ **SAFE:** Your SPI is at or above zero. No drought.")
        status = "Safe"

    # Category B: Clearly in Drought
    elif latest_spi < -1:
        st.error("🚨 **DROUGHT:** Your SPI is below -1.")
        status = "Drought"

        if latest_spi > -1.5:
            st.write("Classification: Moderate drought (SPI between -1 and -1.5)")
        elif latest_spi > -2:
            st.write("Classification: Severe drought (SPI between -1.5 and -2)")
        else:
            st.write("Classification: Extreme drought (SPI below -2)")

    # Category C: Grey Zone (SPI between -1 and 0)
    else:
        status = "Grey Zone"

        # Look backward through the SPI record to determine how we got here
        historical_spi = latest_valid.iloc[::-1]

        found_crossing = False
        # Skip the first value since it is the current month
        for past_spi in historical_spi.iloc[1:]:
            if past_spi >= 0:
                st.warning("⚠️ **DRY SPELL:** Your SPI is below normal, but you have not entered a drought recently.")
                found_crossing = True
                status = "Dry Spell"
                break
            elif past_spi < -1:
                st.warning("⚠️ **RECOVERING:** You are currently out of severe drought, but have not reached full recovery (SPI = 0). You are still in a drought event.")
                found_crossing = True
                status = "Recovering"
                break

        # Fallback if loop finishes without finding a crossing
        if not found_crossing:
            st.warning("⚠️ **UNCERTAIN HISTORY:** Your SPI is below normal but your record is too short to determine whether this is a new dry spell or recovery from a prior drought.")
            status = "Uncertain"

    # --- Duration Calculation ---
    if status in ["Drought", "Recovering"]:
        duration_counter = 0
        historical_spi_all = latest_valid.iloc[::-1]

        for past_spi in historical_spi_all:
            if past_spi < 0:
                duration_counter += 1
            else:
                break

        st.write(f"⏳ **Duration:** This current deficit event has lasted for **{duration_counter} months**.")

        with st.expander("How do we calculate this?"):
            st.write("A drought does not end just because one month is slightly better. We consider a drought event active until the SPI-12 value fully returns to zero or above.")
