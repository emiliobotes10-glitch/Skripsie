import streamlit as st
import pandas as pd
import numpy as np
import datetime
import xarray as xr
import scipy.stats as stats
import requests
import re
import rasterio

# ---------- App setup ----------
st.set_page_config(page_title="Combined Drought Tracker V0", layout="centered")

@st.cache_data
def geocode_place(place_name):
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

def show_location_map(lat, lon):
    """Draw a pin at the chosen location so the user can sanity-check it."""
    if lat == 0.0 and lon == 0.0:
        return
    st.map(pd.DataFrame({"lat": [lat], "lon": [lon]}), zoom=8, size=2000)
    st.caption(f"Check the pin: Lat {lat:.4f}, Lon {lon:.4f}")

if "path" not in st.session_state:
    st.session_state["path"] = None

def reset_app():
    st.session_state["path"] = None
    st.rerun()

# ---------- Landing page ----------
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

# ---------- SAWS upload path ----------
elif st.session_state["path"] == "upload":
    
    if st.button("Start Over", on_click=reset_app):
        pass

    st.title("Drought Tracker: Upload SAWS Data")
    st.markdown("### Notice: This application uses your 12-month cumulative rainfall to check for drought conditions based on pre-computed precipitation thresholds (Smith, 2023).")

    st.markdown("#### Step 1: Enter your location")
    
    location_choice = st.radio("How would you like to set your location?", ["Search by City/Town", "Enter Coordinates"], key="loc_2a")
    
    user_lat, user_lon = 0.0, 0.0
    
    if location_choice == "Search by City/Town":
        place_name = st.text_input("Enter city or town name:")
        if place_name:
            results = geocode_place(place_name)
            if results:
                options = {}
                for r in results:
                    admin = r.get('admin1', '')
                    country = r.get('country', '')
                    name = r.get('name', '')
                    label = f"{name}"
                    if admin: label += f", {admin}"
                    if country: label += f", {country}"
                    label = f"{label} (Lat: {r['latitude']:.2f}, Lon: {r['longitude']:.2f})"
                    options[label] = (r['latitude'], r['longitude'])
                
                selected_label = st.selectbox("Select the correct match:", list(options.keys()), key="sel_2a")
                user_lat, user_lon = options[selected_label]
                st.success(f"Location set: Lat {user_lat:.4f}, Lon {user_lon:.4f}")
            else:
                st.error("Could not find this place.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            user_lat = st.number_input("Enter Latitude (e.g., -33.8000)", value=0.0, format="%.4f")
        with col2:
            user_lon = st.number_input("Enter Longitude (e.g., 19.8000)", value=0.0, format="%.4f")

    # --- Map check for the location entered in Step 1 ---
    show_location_map(user_lat, user_lon)
    step1_lat, step1_lon = user_lat, user_lon

    st.markdown("#### Step 2: Upload SAWS Data")
    st.markdown("Please upload your historical South African Weather Service (SAWS) rainfall data below. A minimum of 12 months of data is required.")
    uploaded_file = st.file_uploader("Upload your SAWS Excel file (.xlsx, .xls)", type=['xlsx', 'xls'])

    if uploaded_file is not None:
        rain_data = pd.read_excel(uploaded_file)
        
        # --- Location check (only runs if the file contains SAWS-style metadata) ---
        file_lat, file_lon = None, None
        if 'Unnamed: 0' in rain_data.columns:
            for value in rain_data['Unnamed: 0'].dropna().map(str):
                if "Daily Rain (mm) Data for station" in value:
                    matches = re.findall(r'-?\d+\.\d+', value)
                    if len(matches) >= 2:
                        file_lat, file_lon = float(matches[0]), float(matches[1])
                        break

        if file_lat is not None and file_lat > 0:
            file_lat = -file_lat

        if file_lat is not None:
            if user_lat == 0.0 and user_lon == 0.0:
                user_lat, user_lon = file_lat, file_lon
                st.info(f"Using station location from file: {file_lat}, {file_lon}")
            elif abs(user_lat - file_lat) > 0.1 or abs(user_lon - file_lon) > 0.1:
                st.warning(f"Your location ({user_lat:.4f}, {user_lon:.4f}) doesn't match "
                           f"the station in the file ({file_lat}, {file_lon}). "
                           f"Thresholds will be taken from the location you use.")
                if st.checkbox("Use the file's station coordinates instead", value=True):
                    user_lat, user_lon = file_lat, file_lon
            else:
                st.success("Your location matches the station in the file.")

        # --- Map check again if the file changed the location that will be used ---
        if (user_lat, user_lon) != (step1_lat, step1_lon):
            st.markdown("**Location that will be used for the thresholds:**")
            show_location_map(user_lat, user_lon)

        # --- Cut-off date: SAWS extraction date from the year-block headers ---
        # Days after this date had not happened yet when the file was extracted,
        # so they are excluded from both the missing-data % and the analysis.
        cutoff_date = None
        if 'Unnamed: 0' in rain_data.columns:
            for value in rain_data['Unnamed: 0'].dropna().map(str):
                if "Daily Rain" in value:
                    match = re.search(r'Extracted\s+(\d{4})/(\d{1,2})/(\d{1,2})', value)
                    if match:
                        try:
                            header_date = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                        except ValueError:
                            continue
                        if cutoff_date is None or header_date > cutoff_date:
                            cutoff_date = header_date

        if cutoff_date is not None:
            st.info(f"Data analysed up to {cutoff_date.strftime('%d %B %Y')} (SAWS extraction date).")
        else:
            st.info("No extraction date found in file. Analysing to the end of the file.")

        cell_Count = 0
        value_Count = 0
        current_year = 0
        has_warning = False 
        missing_flags = ["***", "----", "A", "B", "---", "="]
        
        for index, row in rain_data.iterrows():
            first_col_value = str(row.get('Unnamed: 0', ''))
            
            if "Daily Rain" in first_col_value:
                words = first_col_value.split()
                for i, word in enumerate(words):
                    if word.isdigit() and len(word) == 4:
                        if (i + 1) < len(words) and words[i + 1] == "m":
                            continue
                        else:
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
                    if column_name not in row:
                        continue
                        
                    try:
                        actual_date = datetime.date(current_year, current_month, current_day)
                    except ValueError:
                        continue

                    if cutoff_date is not None and actual_date > cutoff_date:
                        continue

                    cell_Count += 1

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
            st.error(f"Data rejected. Your percentage of missing data ({percentage_missing:.2f}%) is > 15%. Cannot yield accurate results.")
            st.stop()
            
        elif 10.0 <= percentage_missing <= 15.0:
            st.warning(f"Warning: Missing data is between 10-15%. Proceeding, but results may be less reliable.")
            has_warning = True 
            
        else:
            st.success("Data quality is good (< 10% missing).")

        clean_dates = []
        clean_rainfall = []
        
        for index, row in rain_data.iterrows():
            first_col_value = str(row.get('Unnamed: 0', ''))
            
            if "Daily Rain" in first_col_value:
                words = first_col_value.split()
                for i, word in enumerate(words):
                    if word.isdigit() and len(word) == 4:
                        if (i + 1) < len(words) and words[i + 1] == "m":
                            continue
                        else:
                            current_year = int(word)
                            break 

            if first_col_value.isdigit() and 1 <= int(first_col_value) <= 31:
                current_day = int(first_col_value)
                
                for current_month, column_name in month_columns:
                    if column_name not in row:
                        continue
                        
                    try:
                        actual_date = datetime.date(current_year, current_month, current_day)
                    except ValueError:
                        continue

                    if cutoff_date is not None and actual_date > cutoff_date:
                        continue

                    clean_dates.append(actual_date)

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
        #right here m8
        def apply_monthly_data_rule(monthly_series):
            total_days = len(monthly_series)
            valid_days = monthly_series.notna().sum()
            missing_days = total_days - valid_days

            # Find longest consecutive missing period
            max_consecutive_missing = 0
            current_streak = 0

            for value in monthly_series:
                if pd.isna(value):
                    current_streak += 1
                    max_consecutive_missing = max(
                        max_consecutive_missing,
                        current_streak
                    )
                else:
                    current_streak = 0

            # WMO-based missing-data rule
            if missing_days >= 11 or max_consecutive_missing >= 5:
                return np.nan

            elif missing_days > 0:
                observed_sum = monthly_series.sum()
                return observed_sum * (total_days / valid_days)

            else:
                return monthly_series.sum()


        monthly_stats = (
            daily_df
            .groupby(pd.Grouper(key='Date', freq='ME'))['Rainfall_mm']
            .apply(apply_monthly_data_rule)
            .reset_index(name='Total_Monthly_Rain')
        )

        monthly_stats = monthly_stats.rename(
            columns={'Date': 'Month_Date'}
        )


        # Exclude the current/latest calendar month if it is incomplete
        if not monthly_stats.empty:
            latest_month = monthly_stats['Month_Date'].iloc[-1]

            days_in_latest_month = latest_month.days_in_month

            latest_month_data = daily_df[
                (daily_df['Date'].dt.year == latest_month.year) &
                (daily_df['Date'].dt.month == latest_month.month)
            ]

            # Days present in the file for this month (including flagged/missing days).
            # A month is incomplete only if the data stops before the month ends;
            # missing days inside a finished month are left to the WMO rule.
            days_present_latest = len(latest_month_data)

            if days_present_latest < days_in_latest_month:
                last_month_str = latest_month.strftime('%B %Y')

                st.warning(
                    f"**Data Adjusted:** The current month ({last_month_str}) "
                    f"is incomplete ({int(days_present_latest)}/{int(days_in_latest_month)} "
                    f"days in file). It has been excluded from the analysis."
                )

                monthly_stats = monthly_stats[
                    monthly_stats['Month_Date'] != latest_month
                ]


        monthly_stats = monthly_stats.set_index('Month_Date')

        total_months = len(monthly_stats)
        if total_months < 12:
            st.error(f"Insufficient data. You only have {total_months} months of data. Exactly 12 months minimum required.")
            st.stop()
        
        timescale = 12
        monthly_stats['Rolling_12_Month_Rainfall'] = monthly_stats['Total_Monthly_Rain'].rolling(window=timescale, min_periods=timescale).sum()

        st.markdown("### Your Cumulative Rainfall Results")
        st.dataframe(monthly_stats[['Total_Monthly_Rain', 'Rolling_12_Month_Rainfall']])
        
        if has_warning:
            st.warning("**Reminder:** Due to the missing data percentage (10-15%) in your upload, this final cumulative sum may be slightly underestimated.")

        st.markdown("---")
        st.markdown("### Step 3: Check Against Thresholds")
        st.markdown("Extract the expected 12-month precipitation threshold for your location based on Smith's (2023) interpolated raster data.")
        
        tif_normal_path = "SPI12_0.tif" 
        tif_drought_path = "SPI12_NEG1.tif"

        if st.button("Check Drought Status", type="primary"):
            if user_lat == 0.0 and user_lon == 0.0:
                st.error("Please enter a valid Latitude and Longitude in Step 1.")
            elif not (-35.0 <= user_lat <= -22.0 and 16.0 <= user_lon <= 33.0):
                st.error("Coordinates are outside South Africa bounds (-35 to -22 lat, 16 to 33 lon).")
            else:
                try:
                    with rasterio.open(tif_normal_path) as dataset_norm, rasterio.open(tif_drought_path) as dataset_drought:
                        for val in dataset_norm.sample([(user_lon, user_lat)]):
                            threshold_normal = val[0]
                        for val in dataset_drought.sample([(user_lon, user_lat)]):
                            threshold_drought = val[0]
                    
                    if threshold_normal < 0 or threshold_drought < 0:
                         st.error("Error: The coordinates provided returned an invalid value. Make sure your coordinates are within South Africa.")
                    else:
                        st.info(f"**Normal Threshold (SPI=0):** {threshold_normal:.1f} mm | **Drought Threshold (SPI=-1):** {threshold_drought:.1f} mm")
                        
                        st.markdown("#### Historical 12-Month Rainfall vs. Thresholds")
                        
                        chart_data = monthly_stats[['Rolling_12_Month_Rainfall']].copy()
                        chart_data['Normal Threshold (SPI=0)'] = threshold_normal
                        chart_data['Drought Threshold (SPI=-1)'] = threshold_drought
                        
                        st.line_chart(chart_data)
                        
                        valid_sum_idx = monthly_stats['Rolling_12_Month_Rainfall'].last_valid_index()
                        
                        if valid_sum_idx is not None:
                            latest_data_row = monthly_stats.loc[valid_sum_idx]
                            latest_rainfall = latest_data_row['Rolling_12_Month_Rainfall']
                            latest_month_name = latest_data_row.name.strftime('%B %Y')
                            
                            st.write(f"**Your most recent 12-month rainfall ({latest_month_name}):** {latest_rainfall:.1f} mm")
                            
                            # =========================================================
                            # STATUS + HISTORICAL GAP LOGIC
                            # =========================================================

                            status = ""

                            # ---------------------------------------------------------
                            # CURRENT STATUS
                            # ---------------------------------------------------------
                            if latest_rainfall >= threshold_normal:
                                st.success("**SAFE:** Your rainfall is above normal.")
                                status = "Safe"

                            elif latest_rainfall < threshold_drought:
                                st.error("**DROUGHT:** Your rainfall is below the moderate drought threshold.")
                                status = "Drought"

                            else:
                                # Current rainfall is below normal but not drought
                                status = "Grey Zone"

                                # KEEP THE TIMELINE INTACT — DO NOT DROP NaNs
                                historical_series = (
                                    monthly_stats.loc[:valid_sum_idx, 'Rolling_12_Month_Rainfall']
                                    .iloc[::-1]
                                )

                                latest_val = historical_series.iloc[0]
                                previous_values = historical_series.iloc[1:]

                                # -----------------------------------------------------
                                # PHASE A: HISTORICAL STATUS CLASSIFICATION
                                # -----------------------------------------------------
                                gap_found = False
                                found_crossing = False

                                for past_val in previous_values:

                                    # A missing value means there is a data gap.
                                    # Keep searching, but remember that continuity
                                    # can no longer be confirmed.
                                    if pd.isna(past_val):
                                        gap_found = True
                                        continue

                                    # Previous valid value is normal / above normal
                                    elif past_val >= threshold_normal:

                                        if gap_found:
                                            st.warning(
                                                "**UNCERTAIN HISTORY:** Your rainfall is below normal, "
                                                "but a data gap separates the current condition from "
                                                "the last normal/above-normal observation. Continuity "
                                                "of the dry spell cannot be confirmed."
                                            )
                                            status = "Uncertain"

                                        else:
                                            st.warning(
                                                "**DRY SPELL:** You are below normal, but you have not "
                                                "entered a drought recently."
                                            )
                                            status = "Dry Spell"

                                        found_crossing = True
                                        break

                                    # Previous valid value is drought
                                    elif past_val < threshold_drought:

                                        if gap_found:
                                            st.warning(
                                                "**UNCERTAIN HISTORY:** Your rainfall is below normal, "
                                                "but a data gap separates the current condition from "
                                                "the previous drought. Continuity of the recovery "
                                                "cannot be confirmed."
                                            )
                                            status = "Uncertain"

                                        else:
                                            st.warning(
                                                "**RECOVERING:** You are currently out of severe drought, "
                                                "but have not reached full recovery (Normal). You are "
                                                "still in a drought event."
                                            )
                                            status = "Recovering"

                                        found_crossing = True
                                        break

                                    # Previous value is also in the grey zone
                                    else:
                                        continue

                                if not found_crossing:
                                    st.warning(
                                        "**UNCERTAIN HISTORY:** Your rainfall is below normal but "
                                        "your record is too short to determine whether this is a new "
                                        "dry spell or recovery from a prior drought."
                                    )
                                    status = "Uncertain"


                            # =========================================================
                            # CONTINUOUS DEFICIT DURATION + DATA GAP CALCULATION
                            # =========================================================

                            if status in ["Drought", "Recovering"]:

                                # KEEP ALL MONTHS, INCLUDING NaNs
                                historical_series_with_nans = (
                                    monthly_stats.loc[:valid_sum_idx, 'Rolling_12_Month_Rainfall']
                                    .iloc[::-1]
                                )

                                latest_val = historical_series_with_nans.iloc[0]
                                previous_values = historical_series_with_nans.iloc[1:]

                                # Count the current month as part of the
                                # continuous deficit duration if it is below normal.
                                continuous_deficit_duration = (
                                    1 if latest_val < threshold_normal else 0
                                )

                                gap_length = 0
                                pre_gap_val = None
                                pre_gap_date = None
                                hit_gap = False
                                found_start = False

                                # -----------------------------------------------------
                                # Walk backwards through the COMPLETE timeline
                                # -----------------------------------------------------
                                for past_date, past_val in previous_values.items():

                                    # -------------------------------
                                    # DATA GAP
                                    # -------------------------------
                                    if pd.isna(past_val):

                                        hit_gap = True
                                        gap_length += 1
                                        continue

                                    # -----------------------------------------
                                    # BEFORE THE GAP:
                                    # count only truly continuous deficit months
                                    # -----------------------------------------
                                    if hit_gap is False:

                                        if past_val < threshold_normal:
                                            continuous_deficit_duration += 1

                                        else:
                                            # Normal/above-normal ends the current
                                            # continuous deficit event
                                            found_start = True
                                            break

                                    # -----------------------------------------
                                    # AFTER THE GAP:
                                    # find first valid pre-gap observation
                                    # -----------------------------------------
                                    else:

                                        pre_gap_val = past_val
                                        pre_gap_date = past_date
                                        break


                                # =====================================================
                                # GAP INTERPRETATION
                                # =====================================================

                                if hit_gap:

                                    st.write(
                                        f"**Confirmed continuous deficit duration:** "
                                        f"{continuous_deficit_duration} months"
                                    )

                                    st.write(
                                        f"**Data gap:** {gap_length} months"
                                    )

                                    if pre_gap_val is not None:

                                        st.write(
                                            f"**Last available pre-gap observation:** "
                                            f"{pre_gap_date.strftime('%B %Y')} "
                                            f"({pre_gap_val:.2f})"
                                        )

                                        # -------------------------------------------------
                                        # PRE-GAP = DROUGHT
                                        # -------------------------------------------------
                                        if pre_gap_val < threshold_drought:

                                            st.write(
                                                "**Pre-Gap Context:** Drought."
                                            )

                                        # -------------------------------------------------
                                        # PRE-GAP = NORMAL / ABOVE NORMAL
                                        # -------------------------------------------------
                                        elif pre_gap_val >= threshold_normal:

                                            st.write(
                                                "**Pre-Gap Context:** Normal/Above Normal."
                                            )

                                        # -------------------------------------------------
                                        # PRE-GAP = GREY ZONE
                                        # -------------------------------------------------
                                        else:

                                            st.write(
                                                "**Pre-Gap Context:** Grey Zone "
                                                "(below normal, but not drought)."
                                            )

                                    else:

                                        st.write(
                                            "**Pre-Gap Context:** No valid rainfall value "
                                            "was found before the data gap."
                                        )

                                # =====================================================
                                # NO GAP — STANDARD DURATION CALCULATION
                                # =====================================================
                                else:

                                    if found_start:

                                        st.write(
                                            f"**Continuous deficit duration:** "
                                            f"This current deficit event has lasted for "
                                            f"**{continuous_deficit_duration} months**."
                                        )

                                    else:

                                        st.write(
                                            f"**Continuous deficit duration:** At least "
                                            f"**{continuous_deficit_duration} months**. "
                                            "The event began before the start of your record, so "
                                            "the true duration is likely longer."
                                        )

                        else:
                            st.error("Cannot calculate status: There are no valid 12-month periods in your dataset.")
    
                except FileNotFoundError:
                    st.error("Threshold raster files not found.")
                except Exception as e:
                    st.error(f"An error occurred while reading the spatial data: {e}")

# ---------- CHIRPS satellite path ----------
elif st.session_state["path"] == "chirps":
    
    if st.button("Start Over", on_click=reset_app):
        pass

    st.title("CHIRPS Drought Tracker")
    st.markdown("### Notice: This application uses CHIRPS satellite rainfall data to calculate SPI-12 at any location in South Africa.")
    st.markdown("No rainfall file upload is needed. Just enter your coordinates.")

    st.markdown("#### Enter your location")
    
    location_choice_b = st.radio("How would you like to set your location?", ["Search by City/Town", "Enter Coordinates"], key="loc_2b")
    
    user_lat, user_lon = -33.7609, 19.4741
    
    if location_choice_b == "Search by City/Town":
        place_name = st.text_input("Enter city or town name:")
        if place_name:
            results = geocode_place(place_name)
            if results:
                options = {}
                for r in results:
                    admin = r.get('admin1', '')
                    country = r.get('country', '')
                    name = r.get('name', '')
                    label = f"{name}"
                    if admin: label += f", {admin}"
                    if country: label += f", {country}"
                    label = f"{label} (Lat: {r['latitude']:.2f}, Lon: {r['longitude']:.2f})"
                    options[label] = (r['latitude'], r['longitude'])
                
                selected_label = st.selectbox("Select the correct match:", list(options.keys()), key="sel_2b")
                user_lat, user_lon = options[selected_label]
                st.success(f"Location set: Lat {user_lat:.4f}, Lon {user_lon:.4f}")
            else:
                st.error("Could not find this place.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            user_lat = st.number_input("Latitude (e.g., -33.7609)", value=-33.7609, format="%.4f")
        with col2:
            user_lon = st.number_input("Longitude (e.g., 19.4741)", value=19.4741, format="%.4f")

    # --- Map check for the chosen location ---
    show_location_map(user_lat, user_lon)

    if st.button("Run SPI Calculation", type="primary"):

        if not (-35.0 <= user_lat <= -22.0 and 16.0 <= user_lon <= 33.0):
            st.error("Coordinates are outside South Africa. Please check your latitude and longitude.")
            st.stop()

        try:
            ds = xr.open_dataset("chirps_sa_monthly.nc")
        except FileNotFoundError:
            st.error("CHIRPS data file not found.")
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
            st.error("No rainfall data found at this location. The coordinate may be outside the CHIRPS land coverage.")
            st.stop()

        st.success(f"Extracted {len(monthly_df.dropna())} months of CHIRPS data.")

        timescale = 12
        monthly_df["Rolling_12_Month_Rainfall"] = monthly_df["Monthly_Rain"].rolling(
            window=timescale, min_periods=timescale
        ).sum()

        monthly_df["SPI_12"] = np.nan
        spi_0_thresholds, spi_minus_1_thresholds = [], []

        for month in range(1, 13):
            month_data = monthly_df[monthly_df.index.month == month]["Rolling_12_Month_Rainfall"].dropna()

            if month_data.empty:
                continue

            # Mixed distribution H(x) = q + (1 - q) * G(x): q is the probability of zero rainfall,
            # G is a gamma distribution fitted to the non-zero 12-month totals
            q = (month_data == 0).sum() / len(month_data)
            month_positive = month_data[month_data > 0]

            if month_positive.empty:
                continue

            shape, _, scale = stats.gamma.fit(month_positive, floc=0)

            # Convert each 12-month total to SPI
            H = q + (1 - q) * stats.gamma.cdf(month_data, shape, loc=0, scale=scale)
            monthly_df.loc[month_data.index, "SPI_12"] = stats.norm.ppf(H)

            # Invert the distribution to find the rainfall that corresponds to SPI = 0 and SPI = -1
            month_thresholds = []
            for target_p in [stats.norm.cdf(0), stats.norm.cdf(-1)]:  # 0.5 and 0.158655
                if target_p <= q:
                    threshold = 0.0
                else:
                    threshold = stats.gamma.ppf((target_p - q) / (1 - q), shape, loc=0, scale=scale)
                month_thresholds.append(threshold)

            spi_0_thresholds.append(month_thresholds[0])
            spi_minus_1_thresholds.append(month_thresholds[1])

        if spi_0_thresholds and spi_minus_1_thresholds:
            threshold_normal = np.mean(spi_0_thresholds)
            threshold_drought = np.mean(spi_minus_1_thresholds)
        else:
            threshold_normal = 0
            threshold_drought = 0

        st.info(f"**CHIRPS Precipitation Thresholds (Smith Method - Averaged over 12 months):**")
        st.write(f"Normal (SPI=0): **{threshold_normal:.1f} mm** | Drought (SPI=-1): **{threshold_drought:.1f} mm**")

        st.markdown("### CHIRPS SPI-12 Results (Last 24 Months)")
        display_df = monthly_df.tail(24)
        st.dataframe(display_df)

        csv_data = monthly_df.to_csv()
        st.download_button(
            label="Download Full SPI-12 Results (CSV)",
            data=csv_data,
            file_name="CHIRPS_SPI12_Results.csv",
            mime="text/csv"
        )

        st.markdown("---")
        # --- Step 2: Drought Status ---

        # CHIRPS SPI thresholds
        normal_thresh = 0
        drought_thresh = -1

        # -------------------------------------------------
        # TIMELINE SETUP - KEEP NaNs INTACT
        # -------------------------------------------------
        valid_idx = monthly_df["SPI_12"].last_valid_index()

        if valid_idx is None:
            st.error("Could not calculate SPI. Insufficient valid data.")
            st.stop()

        latest_spi = monthly_df.loc[valid_idx, "SPI_12"]
        latest_date = valid_idx.strftime("%B %Y")
        latest_rainfall = monthly_df.loc[
            valid_idx, "Rolling_12_Month_Rainfall"
        ]

        st.markdown("#### Historical 12-Month Rainfall vs. Averaged Thresholds")
        chart_data = monthly_df[["Rolling_12_Month_Rainfall"]].copy()
        chart_data["Normal (SPI=0 Average)"] = threshold_normal
        chart_data["Drought (SPI=-1 Average)"] = threshold_drought
        st.line_chart(chart_data)

        st.markdown("#### Historical SPI-12")
        spi_chart = monthly_df[["SPI_12"]].copy()
        spi_chart["SPI = 0 (Normal)"] = 0.0
        spi_chart["SPI = -1 (Drought)"] = -1.0
        st.line_chart(spi_chart)

        st.markdown(f"**Most recent month:** {latest_date}")
        st.markdown(f"**12-month cumulative rainfall:** {latest_rainfall:.1f} mm")
        st.markdown(f"**SPI-12 value:** {latest_spi:.2f}")

        historical_spi_series = (
            monthly_df.loc[:valid_idx, "SPI_12"]
            .iloc[::-1]
        )

        # -------------------------------------------------
        # STATUS CLASSIFICATION
        # -------------------------------------------------

        status = ""

        # Current SPI >= 0
        if latest_spi >= normal_thresh:

            st.success(
                "**SAFE:** Your SPI is at or above zero. No drought."
            )

            status = "Safe"

        # Current SPI < -1
        elif latest_spi < drought_thresh:

            st.error(
                "**DROUGHT:** Your SPI is below -1."
            )

            status = "Drought"

            # Keep your existing drought severity classification
            if latest_spi > -1.5:
                st.write(
                    "Classification: Moderate drought "
                    "(SPI between -1 and -1.5)"
                )
            elif latest_spi > -2:
                st.write(
                    "Classification: Severe drought "
                    "(SPI between -1.5 and -2)"
                )
            else:
                st.write(
                    "Classification: Extreme drought "
                    "(SPI below -2)"
                )

        # Current SPI is in the grey zone
        else:

            found_crossing = False
            hit_gap_in_status = False

            # Skip the current month because latest_spi is
            # already known.
            for past_spi in historical_spi_series.iloc[1:]:

                # A NaN means there is a data blackout.
                # Do not stop searching; continue backwards.
                if pd.isna(past_spi):

                    hit_gap_in_status = True
                    continue

                # Previous valid SPI is normal / above normal
                if past_spi >= normal_thresh:

                    if hit_gap_in_status:

                        st.warning(
                            "**CURRENT: BELOW NORMAL**\n\n"
                            "Previous available SPI indicated normal "
                            "or above-normal conditions, but a data gap "
                            "prevents confirmation of the dry-spell history."
                        )

                        status = "Uncertain"

                    else:

                        st.warning(
                            "**DRY SPELL:** Your SPI is below normal, "
                            "but you have not entered a drought recently."
                        )

                        status = "Dry Spell"

                    found_crossing = True
                    break

                # Previous valid SPI is drought
                elif past_spi < drought_thresh:

                    if hit_gap_in_status:

                        st.warning(
                            "**CURRENT: BELOW NORMAL**\n\n"
                            "Previous available SPI indicated drought, "
                            "but a data gap prevents confirmation of the "
                            "recovery history."
                        )

                        status = "Uncertain"

                    else:

                        st.warning(
                            "**RECOVERING:** You are currently out of "
                            "severe drought, but have not reached full "
                            "recovery (SPI = 0). You are still in a "
                            "drought event."
                        )

                        status = "Recovering"

                    found_crossing = True
                    break

                # Previous valid SPI is also in the grey zone
                else:

                    # Keep searching backwards.
                    continue

            # No normal/drought crossing was found
            if not found_crossing:

                st.warning(
                    "**UNCERTAIN HISTORY:** Your SPI is below normal "
                    "but your record is too short to determine whether "
                    "this is a new dry spell or recovery from a prior drought."
                )

                status = "Uncertain"


        # -------------------------------------------------
        # DURATION CALCULATION
        # -------------------------------------------------

        if status in ["Drought", "Recovering"]:

            continuous_deficit_duration = 0
            found_start = False
            hit_gap = False
            gap_length = 0
            pre_gap_spi = None
            pre_gap_date = None

            # Loop through the complete reversed timeline,
            # including the current month.
            for past_date, past_spi in historical_spi_series.items():

                # -----------------------------------------
                # DATA GAP
                # -----------------------------------------

                if pd.isna(past_spi):

                    hit_gap = True
                    gap_length += 1

                    # From here onward, duration is no longer
                    # considered continuous.
                    continue

                # -----------------------------------------
                # PHASE 1: STRICT CONTINUOUS COUNTER
                # -----------------------------------------

                if hit_gap is False:

                    if past_spi < normal_thresh:

                        continuous_deficit_duration += 1

                    else:

                        found_start = True
                        break

                # -----------------------------------------
                # PHASE 2: HISTORICAL SCOUT
                # -----------------------------------------

                else:

                    # First valid SPI before the data gap
                    pre_gap_spi = past_spi
                    pre_gap_date = past_date
                    break

            # -------------------------------------------------
            # DISPLAY RESULTS
            # -------------------------------------------------

            if found_start:

                st.write(
                    f"**Continuous deficit duration:** This current deficit event has "
                    f"lasted for **{continuous_deficit_duration} months**."
                )

            elif hit_gap:

                st.write(
                    f"**Confirmed continuous deficit duration:** "
                    f"{continuous_deficit_duration} months"
                )

                st.write(
                    f"**Data gap:** {gap_length} months"
                )

                if pre_gap_spi is not None:

                    st.write(
                        f"**Last available pre-gap observation:** "
                        f"{pre_gap_date.strftime('%B %Y')} "
                        f"(SPI = {pre_gap_spi:.2f})"
                    )

                    # -----------------------------------------
                    # PRE-GAP SPI = DROUGHT
                    # -----------------------------------------

                    if pre_gap_spi <= drought_thresh:

                        st.write(
                            "**Pre-Gap Context:** Drought."
                        )

                    # -----------------------------------------
                    # PRE-GAP SPI = GREY ZONE
                    # -----------------------------------------

                    elif drought_thresh < pre_gap_spi < normal_thresh:

                        st.write(
                            "**Pre-Gap Context:** Grey Zone "
                            "(below normal, but not drought)."
                        )

                    # -----------------------------------------
                    # PRE-GAP SPI = NORMAL / ABOVE NORMAL
                    # -----------------------------------------

                    elif pre_gap_spi >= normal_thresh:

                        st.write(
                            "**Pre-Gap Context:** Normal/Above Normal."
                        )

                else:

                    st.write(
                        "**Pre-Gap Context:** No valid SPI was found "
                        "before the data gap."
                    )

            else:

                st.write(
                    f"**Continuous deficit duration:** At least "
                    f"**{continuous_deficit_duration} months**. "
                    "The continuous deficit extends to the earliest "
                    "valid SPI-12 value in the record."
                )
