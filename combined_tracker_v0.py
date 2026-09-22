import streamlit as st
import pandas as pd
import numpy as np
import datetime
import xarray as xr
import scipy.stats as stats
import spei
import requests

# ==========================================
# PHASE 0: APP CONFIG & SESSION STATE
# ==========================================
st.set_page_config(page_title="Combined Drought Tracker V0", layout="centered")

@st.cache_data
def geocode_place(place_name):
    """Fetches up to 5 location matches from Open-Meteo's Geocoding API."""
    url = f"https://geocoding-api.open-meteo.com/v1/search?name={place_name}&count=5"
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        if "results" in data:
            return data["results"]
        return []
    except Exception:
        return []

# Initialize session state to track which path the user has chosen.
if "path" not in st.session_state:
    st.session_state["path"] = None

# Optional Helper: A function to reset the app back to the landing screen
def reset_app():
    st.session_state["path"] = None
    st.rerun()

# ==========================================
# PHASE 1: LANDING SCREEN
# ==========================================
if st.session_state["path"] is None:
    st.title("Are You In A Drought?")
    st.markdown("### Do you have at least 12 months of rainfall data?")
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button("Yes — Upload My Rainfall Data", use_container_width=True):
            st.session_state["path"] = "upload"
            st.rerun()
        st.info("Upload your SAWS Excel file. Rainfall gauge data with pre-computed precipitation thresholds (Smith, 2023). Rainfall gauges SPI up to date to 2021 rainfall data.")
            
    with col2:
        if st.button("No — Use CHIRPS Satellite Data", use_container_width=True):
            st.session_state["path"] = "chirps"
            st.rerun()
        st.info("No file needed — just enter your coordinates. Up-to-date data to 2026. Note: CHIRPS satellite data often tends to overestimate low amounts of rainfall and underestimate high amounts of rainfall.")

# ==========================================
# PHASE 2A: UPLOAD PATH (SAWS DATA)
# ==========================================
elif st.session_state["path"] == "upload":
    
    # Allow user to go back to the main menu
    if st.button("← Start Over", on_click=reset_app):
        pass

    st.title("Drought Tracker: Upload SAWS Data")
    st.markdown("### ⚠️ Notice: This application uses your 12-month cumulative rainfall to check for drought conditions based on pre-computed precipitation thresholds (Smith, 2023).")

    # --- 2A.1: User Inputs ---
    st.markdown("#### Step 1: Enter your location")
    
    location_choice = st.radio("How would you like to set your location?", ["Search by City/Town", "Enter Coordinates"], key="loc_2a")
    
    user_lat, user_lon = 0.0, 0.0
    
    if location_choice == "Search by City/Town":
        place_name = st.text_input("Enter city or town name:")
        if place_name:
            results = geocode_place(place_name)
            if results:
                # Format results for the selectbox
                options = {}
                for r in results:
                    admin = r.get('admin1', '')
                    country = r.get('country', '')
                    name = r.get('name', '')
                    
                    label = f"{name}"
                    if admin: label += f", {admin}"
                    if country: label += f", {country}"
                    label = f"{label} (Lat: {r['latitude']:.2f}, Lon: {r['longitude']:.2f})"
                    
                    # Store lat/lon tuple keyed by the display label
                    options[label] = (r['latitude'], r['longitude'])
                
                selected_label = st.selectbox("Select the correct match:", list(options.keys()), key="sel_2a")
                user_lat, user_lon = options[selected_label]
                st.success(f"📍 Location set: Lat {user_lat:.4f}, Lon {user_lon:.4f}")
            else:
                st.error("❌ Could not find this place.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            user_lat = st.number_input("Enter Latitude (e.g., -33.8000)", value=0.0, format="%.4f")
        with col2:
            user_lon = st.number_input("Enter Longitude (e.g., 19.8000)", value=0.0, format="%.4f")

    st.markdown("#### Step 2: Upload SAWS Data")
    st.markdown("Please upload your historical South African Weather Service (SAWS) rainfall data below. A minimum of 12 months of data is required.")
    uploaded_file = st.file_uploader("Upload your SAWS Excel file (.xlsx, .xls)", type=['xlsx', 'xls'])

    if uploaded_file is not None:
        st.info("File uploaded successfully. Scanning data quality...")
        
        # Load the uploaded file from memory into a pandas table
        rain_data = pd.read_excel(uploaded_file)
        
        cell_Count = 0
        value_Count = 0
        current_year = 0
        has_warning = False 
        
        missing_flags = ["***", "----", "A", "B", "---", "="]
        
        # --- 2A.2: Data Quality Scan ---
        for index, row in rain_data.iterrows():
            first_col_value = str(row['Unnamed: 0'])
            
            if "Daily Rain" in first_col_value:
                words = first_col_value.split()
                for word in words:
                    if word.isdigit() and len(word) == 4:
                        current_year = int(word)
                        break 

            if first_col_value.isdigit() and 1 <= int(first_col_value) <= 31:
                current_day = int(first_col_value)
                month_columns = [
                    (1, 'Unnamed: 1'), (2, 'Unnamed: 2'), (3, 'Unnamed: 3'),
                    (4, 'Unnamed: 4'), (5, 'Unnamed: 5'), (6, 'Unnamed: 6'),
                    (7, 'Unnamed: 7'), (8, 'Unnamed: 8'), (9, 'Unnamed: 9'),
                    (10, 'Unnamed: 10'), (11, 'Unnamed: 11'), (12, 'Unnamed: 12')
                ]
                
                for current_month, column_name in month_columns:
                    try:
                        actual_date = datetime.date(current_year, current_month, current_day)
                        cell_Count += 1
                    except ValueError:
                        continue 

                    cell_data = row[column_name]
                    
                    if pd.isna(cell_data) or str(cell_data).strip() == "":
                        value_Count += 1
                    else:
                        text_data = str(cell_data).strip()
                        if text_data in missing_flags:
                            pass
                        elif 'C' in text_data or 'E' in text_data:
                            value_Count += 1
                        else:
                            try:
                                float(text_data)
                                value_Count += 1
                            except ValueError:
                                pass

        if cell_Count == 0:
            st.error("Error: 0 valid calendar days were processed. Check file formatting.")
            st.stop()
        
        missing_Count = cell_Count - value_Count
        percentage_missing = (missing_Count / cell_Count) * 100
        
        st.write(f"**Data Quality Scan:** {percentage_missing:.2f}% of data is marked as missing.")
        
        if percentage_missing > 15.0:
            st.error(f"❌ Data rejected. Your percentage of missing data ({percentage_missing:.2f}%) is > 15%. Cannot yield accurate results.")
            st.stop()
            
        elif 10.0 <= percentage_missing <= 15.0:
            st.warning(f"⚠️ Warning: Missing data is between 10-15%. Proceeding, but results may be less reliable.")
            has_warning = True 
            
        else:
            st.success("✅ Data quality is excellent (< 10% missing). Proceeding to aggregation...")

        # --- 2A.3: Daily Cleaning ---
        st.info("Cleaning daily values and aggregating to monthly totals...")
        
        clean_dates = []
        clean_rainfall = []
        
        for index, row in rain_data.iterrows():
            first_col_value = str(row['Unnamed: 0'])
            
            if "Daily Rain" in first_col_value:
                words = first_col_value.split()
                for word in words:
                    if word.isdigit() and len(word) == 4:
                        current_year = int(word)
                        break 

            if first_col_value.isdigit() and 1 <= int(first_col_value) <= 31:
                current_day = int(first_col_value)
                
                for current_month, column_name in month_columns:
                    try:
                        actual_date = datetime.date(current_year, current_month, current_day)
                        clean_dates.append(actual_date)
                    except ValueError:
                        continue 

                    cell_data = row[column_name]
                    
                    if pd.isna(cell_data) or str(cell_data).strip() == "":
                        clean_rainfall.append(0.0)
                    else:
                        text_data = str(cell_data).strip()
                        
                        if text_data in missing_flags:
                            clean_rainfall.append(np.nan)
                        elif 'C' in text_data:
                            try:
                                clean_rainfall.append(float(text_data.replace('C', '')))
                            except ValueError:
                                clean_rainfall.append(0.0)
                        elif 'E' in text_data:
                            try:
                                clean_rainfall.append(float(text_data.replace('E', '')))
                            except ValueError:
                                clean_rainfall.append(0.0)
                        else:
                            try:
                                clean_rainfall.append(float(text_data))
                            except ValueError:
                                clean_rainfall.append(0.0)

        daily_df = pd.DataFrame({
            'Date': pd.to_datetime(clean_dates),
            'Rainfall_mm': clean_rainfall
        })
        
        # --- 2A.4: Monthly Aggregation ---
        monthly_stats = daily_df.groupby(pd.Grouper(key='Date', freq='ME')).agg(
            Total_Monthly_Rain=('Rainfall_mm', lambda x: x.sum(min_count=1)),
            Valid_Days=('Rainfall_mm', 'count'),
            Days_in_Month=('Rainfall_mm', 'size')
        ).reset_index()
        
        monthly_stats = monthly_stats.rename(columns={'Date': 'Month_Date'})
        
        if not monthly_stats.empty:
            last_valid_idx = monthly_stats['Total_Monthly_Rain'].last_valid_index()
            
            if last_valid_idx is not None:
                last_row = monthly_stats.loc[last_valid_idx]
                
                if last_row['Valid_Days'] < last_row['Days_in_Month']:
                    last_month_str = last_row['Month_Date'].strftime('%B %Y')
                    st.warning(f"⚠️ **Data Adjusted:** The final active month ({last_month_str}) is incomplete ({int(last_row['Valid_Days'])}/{int(last_row['Days_in_Month'])} days recorded). It has been excluded from the analysis.")
                    monthly_stats = monthly_stats.drop(last_valid_idx)

        monthly_stats = monthly_stats.drop(columns=['Valid_Days', 'Days_in_Month'])
        monthly_stats = monthly_stats.set_index('Month_Date')

        # --- 2A.5: 12-Month Rolling Sum ---
        total_months = len(monthly_stats)
        if total_months < 12:
            st.error(f"❌ Insufficient data. You only have {total_months} months of data. Exactly 12 months minimum required.")
            st.stop()
        
        st.info("Calculating 12-Month Cumulative Rainfall...")
        
        timescale = 12
        monthly_stats['Rolling_12_Month_Rainfall'] = monthly_stats['Total_Monthly_Rain'].rolling(window=timescale, min_periods=timescale).sum()

        st.markdown("### 📊 Your Cumulative Rainfall Results")
        st.dataframe(monthly_stats[['Total_Monthly_Rain', 'Rolling_12_Month_Rainfall']])
        
        if has_warning:
            st.warning("⚠️ **Reminder:** Due to the missing data percentage (10-15%) in your upload, this final cumulative sum may be slightly underestimated.")

        # --- 2A.6: Threshold Extraction from Smith Rasters ---
        st.markdown("---")
        st.markdown("### Step 3: Check Against Thresholds")
        st.markdown("Extract the expected 12-month precipitation threshold for your location based on Smith's (2023) interpolated raster data.")
        
        try:
            import rasterio
        except ImportError:
            st.error("❌ The 'rasterio' library is missing. Please run `pip install rasterio`.")
            st.stop()
        
        tif_normal_path = "SPI12_0.tif" 
        tif_drought_path = "SPI12_NEG1.tif"

        if st.button("Check Drought Status", type="primary"):
            if user_lat == 0.0 and user_lon == 0.0:
                st.error("❌ Please enter a valid Latitude and Longitude in Step 1.")
            elif not (-35.0 <= user_lat <= -22.0 and 16.0 <= user_lon <= 33.0):
                st.error("❌ Coordinates are outside South Africa bounds (-35 to -22 lat, 16 to 33 lon).")
            else:
                try:
                    with rasterio.open(tif_normal_path) as dataset_norm, rasterio.open(tif_drought_path) as dataset_drought:
                        for val in dataset_norm.sample([(user_lon, user_lat)]):
                            threshold_normal = val[0]
                        for val in dataset_drought.sample([(user_lon, user_lat)]):
                            threshold_drought = val[0]
                    
                    if threshold_normal < 0 or threshold_drought < 0:
                         st.error("❌ Error: The coordinates provided returned an invalid value. Make sure your coordinates are within South Africa.")
                    else:
                        st.info(f"📍 **Normal Threshold (SPI=0):** {threshold_normal:.1f} mm | **Drought Threshold (SPI=-1):** {threshold_drought:.1f} mm")
                        
                        # --- 2A.7: Chart — Rolling Rainfall vs Thresholds ---
                        st.markdown("#### 📈 Historical 12-Month Rainfall vs. Thresholds")
                        
                        chart_data = monthly_stats[['Rolling_12_Month_Rainfall']].dropna().copy()
                        chart_data['Normal Threshold (SPI=0)'] = threshold_normal
                        chart_data['Drought Threshold (SPI=-1)'] = threshold_drought
                        
                        st.line_chart(chart_data)
                        
                        # --- 2A.8: Drought Classification (mm comparison) ---
                        valid_sum_idx = monthly_stats['Rolling_12_Month_Rainfall'].last_valid_index()
                        
                        if valid_sum_idx is not None:
                            latest_data_row = monthly_stats.loc[valid_sum_idx]
                            latest_rainfall = latest_data_row['Rolling_12_Month_Rainfall']
                            latest_month_name = latest_data_row.name.strftime('%B %Y')
                            
                            st.write(f"🌧️ **Your most recent 12-month rainfall ({latest_month_name}):** {latest_rainfall:.1f} mm")
                            
                            status = ""
                            if latest_rainfall >= threshold_normal:
                                st.success("✅ **SAFE:** Your rainfall is above normal.")
                                status = "Safe"
                            elif latest_rainfall < threshold_drought:
                                st.error("🚨 **DROUGHT:** Your rainfall is below the moderate drought threshold.")
                                status = "Drought"
                            else:
                                status = "Grey Zone"
                                historical_data = monthly_stats.loc[:valid_sum_idx, 'Rolling_12_Month_Rainfall'].dropna().iloc[::-1]
                                
                                found_crossing = False
                                for past_val in historical_data.iloc[1:]:
                                    if past_val >= threshold_normal:
                                        st.warning("⚠️ **DRY SPELL:** You are below normal, but you have not entered a drought recently.")
                                        found_crossing = True
                                        status = "Dry Spell"
                                        break
                                    elif past_val < threshold_drought:
                                        st.warning("⚠️ **RECOVERING:** You are currently out of severe drought, but have not reached full recovery (Normal). You are still in a drought event.")
                                        found_crossing = True
                                        status = "Recovering"
                                        break
                                
                                if not found_crossing:
                                    st.warning("⚠️ **UNCERTAIN HISTORY:** Your rainfall is below normal but your record is too short to determine whether this is a new dry spell or recovery from a prior drought.")
                                    status = "Uncertain"
                            
                            # --- 2A.9: Duration ---
                            if status in ["Drought", "Recovering"]:
                                duration_counter = 0
                                historical_data_all = monthly_stats.loc[:valid_sum_idx, 'Rolling_12_Month_Rainfall'].dropna().iloc[::-1]
                                
                                for past_val in historical_data_all:
                                    if past_val < threshold_normal:
                                        duration_counter += 1
                                    else:
                                        break
                                
                                st.write(f"⏳ **Duration:** This current deficit event has lasted for **{duration_counter} months**.")
                                
                        else:
                            st.error("❌ Cannot calculate status: There are no valid 12-month periods in your dataset.")

                except FileNotFoundError:
                    st.error(f"❌ Could not find a raster file. Ensure both .tif files are uploaded to your repository.")
                except Exception as e:
                    st.error(f"❌ An error occurred while reading the spatial data: {e}")

# ==========================================
# PHASE 2B: CHIRPS PATH (SATELLITE DATA)
# ==========================================
elif st.session_state["path"] == "chirps":
    
    # Allow user to go back to the main menu
    if st.button("← Start Over", on_click=reset_app):
        pass

    st.title("CHIRPS Drought Tracker")
    st.markdown("### ⚠️ Notice: This application uses CHIRPS satellite rainfall data to calculate SPI-12 at any location in South Africa.")
    st.markdown("No rainfall file upload is needed. Just enter your coordinates.")

    # --- 2B.1: User Inputs ---
    st.markdown("#### Enter your location")
    
    location_choice_b = st.radio("How would you like to set your location?", ["Search by City/Town", "Enter Coordinates"], key="loc_2b")
    
    # Defaults for CHIRPS path
    user_lat, user_lon = -33.7609, 19.4741
    
    if location_choice_b == "Search by City/Town":
        place_name = st.text_input("Enter city or town name:")
        if place_name:
            results = geocode_place(place_name)
            if results:
                # Format results for the selectbox
                options = {}
                for r in results:
                    admin = r.get('admin1', '')
                    country = r.get('country', '')
                    name = r.get('name', '')
                    
                    label = f"{name}"
                    if admin: label += f", {admin}"
                    if country: label += f", {country}"
                    label = f"{label} (Lat: {r['latitude']:.2f}, Lon: {r['longitude']:.2f})"
                    
                    # Store lat/lon tuple keyed by the display label
                    options[label] = (r['latitude'], r['longitude'])
                
                selected_label = st.selectbox("Select the correct match:", list(options.keys()), key="sel_2b")
                user_lat, user_lon = options[selected_label]
                st.success(f"📍 Location set: Lat {user_lat:.4f}, Lon {user_lon:.4f}")
            else:
                st.error("❌ Could not find this place.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            user_lat = st.number_input("Latitude (e.g., -33.7609)", value=-33.7609, format="%.4f")
        with col2:
            user_lon = st.number_input("Longitude (e.g., 19.4741)", value=19.4741, format="%.4f")

    if st.button("Run SPI Calculation", type="primary"):

        # --- 2B.2: Coordinate Validation ---
        if not (-35.0 <= user_lat <= -22.0 and 16.0 <= user_lon <= 33.0):
            st.error("❌ Coordinates are outside South Africa bounds. Please check your latitude and longitude.")
            st.stop()

        st.info("Loading CHIRPS satellite data for your location...")

        # --- 2B.3: Extract CHIRPS Data ---
        try:
            ds = xr.open_dataset("chirps_sa_monthly.nc")
        except FileNotFoundError:
            st.error("❌ Could not find 'chirps_sa_monthly.nc'. Make sure the file is in the same folder as this app.")
            st.stop()

        point_data = ds["rainfall"].sel(
            latitude=user_lat,
            longitude=user_lon,
            method="nearest"
        )

        monthly_df = point_data.to_dataframe().reset_index()
        monthly_df = monthly_df.rename(columns={"time": "Month_Date", "rainfall": "Monthly_Rain"})
        monthly_df = monthly_df[["Month_Date", "Monthly_Rain"]].copy()
        
        monthly_df["Month_Date"] = pd.to_datetime(monthly_df["Month_Date"])
        monthly_df = monthly_df.set_index("Month_Date")
        monthly_df = monthly_df.sort_index()

        ds.close()

        if monthly_df["Monthly_Rain"].dropna().empty:
            st.error("❌ No rainfall data found at this location. The coordinate may be outside the CHIRPS land coverage.")
            st.stop()

        st.success(f"✅ Extracted {len(monthly_df.dropna())} months of CHIRPS data.")

        # --- 2B.4: 12-Month Rolling Sum ---
        st.info("Calculating 12-month rolling rainfall sum...")
        timescale = 12
        monthly_df["Rolling_12_Month_Rainfall"] = monthly_df["Monthly_Rain"].rolling(
            window=timescale, min_periods=timescale
        ).sum()

        # --- 2B.5: SPI-12 Calculation ---
        st.info("Fitting distributions per calendar month and calculating SPI-12...")
        spi_values = spei.spi(monthly_df["Rolling_12_Month_Rainfall"], dist=stats.gamma)
        monthly_df["SPI_12"] = spi_values

        # --- 2B.6: Precipitation Threshold Extraction (Smith method) ---
        spi_0_thresholds = []
        spi_minus_1_thresholds = []

        for month in range(1, 13):
            month_data = monthly_df[monthly_df.index.month == month]["Rolling_12_Month_Rainfall"].dropna()
            
            if month_data.empty:
                continue
                
            n_total = len(month_data)
            month_positive = month_data[month_data > 0]
            n_zeros = n_total - len(month_positive)
            
            q = n_zeros / n_total
            
            if not month_positive.empty:
                shape, loc, scale = stats.gamma.fit(month_positive, floc=0)
                
                def get_rainfall_for_prob(target_p):
                    if target_p <= q:
                        return 0.0
                    else:
                        adjusted_p = (target_p - q) / (1.0 - q)
                        return stats.gamma.ppf(adjusted_p, shape, loc, scale)
                
                thresh_0 = get_rainfall_for_prob(0.500)
                thresh_minus_1 = get_rainfall_for_prob(0.1587)
                
                spi_0_thresholds.append(thresh_0)
                spi_minus_1_thresholds.append(thresh_minus_1)

        if spi_0_thresholds and spi_minus_1_thresholds:
            threshold_normal = np.mean(spi_0_thresholds)
            threshold_drought = np.mean(spi_minus_1_thresholds)
        else:
            threshold_normal = 0
            threshold_drought = 0

        st.info(f"📍 **Station Precipitation Thresholds (Smith Method - Averaged over 12 months):**")
        st.write(f"Normal (SPI=0): **{threshold_normal:.1f} mm** | Drought (SPI=-1): **{threshold_drought:.1f} mm**")

        # --- 2B.7: Display Results ---
        st.markdown("### 📊 CHIRPS SPI-12 Results (Last 24 Months)")
        display_df = monthly_df.dropna().tail(24)
        st.dataframe(display_df)

        csv_data = monthly_df.to_csv()
        st.download_button(
            label="📥 Download Full SPI-12 Results (CSV)",
            data=csv_data,
            file_name="CHIRPS_SPI12_Results.csv",
            mime="text/csv"
        )

        # --- 2B.8: Charts (BOTH views) ---
        st.markdown("---")
        st.markdown("### Step 2: Drought Status")

        latest_valid = monthly_df["SPI_12"].dropna()

        if latest_valid.empty:
            st.error("❌ Could not calculate SPI. Insufficient valid data.")
            st.stop()

        # Chart 1: Rolling Rainfall vs Averaged Thresholds
        st.markdown("#### 📈 Historical 12-Month Rainfall vs. Averaged Thresholds")
        chart_data = monthly_df[["Rolling_12_Month_Rainfall"]].dropna().copy()
        chart_data["Normal (SPI=0 Average)"] = threshold_normal
        chart_data["Drought (SPI=-1 Average)"] = threshold_drought
        st.line_chart(chart_data)

        # Chart 2: Historical SPI with reference lines
        st.markdown("#### 📈 Historical SPI-12")
        spi_chart = monthly_df[["SPI_12"]].dropna().copy()
        spi_chart["SPI = 0 (Normal)"] = 0.0
        spi_chart["SPI = -1 (Drought)"] = -1.0
        st.line_chart(spi_chart)

        # --- 2B.9: Drought Classification (SPI comparison) ---
        latest_spi = latest_valid.iloc[-1]
        latest_date = latest_valid.index[-1].strftime("%B %Y")
        latest_rainfall = monthly_df.loc[latest_valid.index[-1], "Rolling_12_Month_Rainfall"]

        st.markdown(f"**Most recent month:** {latest_date}")
        st.markdown(f"**12-month cumulative rainfall:** {latest_rainfall:.1f} mm")
        st.markdown(f"**SPI-12 value:** {latest_spi:.2f}")

        status = ""
        if latest_spi >= 0:
            st.success("✅ **SAFE:** Your SPI is at or above zero. No drought.")
            status = "Safe"
        elif latest_spi < -1:
            st.error("🚨 **DROUGHT:** Your SPI is below -1.")
            status = "Drought"
            if latest_spi > -1.5:
                st.write("Classification: Moderate drought (SPI between -1 and -1.5)")
            elif latest_spi > -2:
                st.write("Classification: Severe drought (SPI between -1.5 and -2)")
            else:
                st.write("Classification: Extreme drought (SPI below -2)")
        else:
            status = "Grey Zone"
            historical_spi = latest_valid.iloc[::-1]

            found_crossing = False
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

            if not found_crossing:
                st.warning("⚠️ **UNCERTAIN HISTORY:** Your SPI is below normal but your record is too short to determine whether this is a new dry spell or recovery from a prior drought.")
                status = "Uncertain"

        # --- 2B.10: Duration ---
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
