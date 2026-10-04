"""Streamlit version of the Drought Tracker.

This file only collects inputs and displays results. All calculations live in
core/, which the phone-app API (api/main.py) uses too, so both always agree.
"""

import pandas as pd
import requests
import streamlit as st

from core import AnalysisError
from core.chirps import analyse_chirps
from core.rainfall import evaluate_rainfall
from core.saws import location_mismatch, prepare_saws, read_saws_excel, read_station_info, resolve_location
from core.templates import prepare_daily, prepare_monthly, read_daily_template

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


# ---------- Rainfall file types ----------
FILE_SAWS = "SAWS daily export"
FILE_DAILY = "Daily rainfall template"
FILE_MONTHLY = "Monthly rainfall template"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def template_download_button(file_name, label):
    """Offer a template file that sits in the app folder (same place as the .tif files)."""
    try:
        with open(file_name, "rb") as f:
            st.download_button(label=label, data=f.read(), file_name=file_name, mime=XLSX_MIME)
    except FileNotFoundError:
        st.error(f"Template file not found: {file_name}")


def stop_with(error):
    """Show what was collected before a failure, then the error, and stop."""
    show(error.messages, exclude=("location",))
    st.error(str(error))
    st.stop()


def show(messages, sections=None, exclude=()):
    """Draw messages from core/ with the matching Streamlit element."""
    for m in messages:
        if sections is not None and m["section"] not in sections:
            continue
        if m["section"] in exclude:
            continue
        {
            "info": st.info,
            "success": st.success,
            "warning": st.warning,
            "error": st.error,
            "write": st.write,
            "markdown": st.markdown,
        }[m["level"]](m["text"])


def location_inputs(key_suffix, default_lat, default_lon, lat_label, lon_label):
    """Town search or coordinates. Returns (lat, lon)."""
    choice = st.radio("How would you like to set your location?", ["Search by City/Town", "Enter Coordinates"], key=f"loc_{key_suffix}")
    user_lat, user_lon = default_lat, default_lon

    if choice == "Search by City/Town":
        place_name = st.text_input("Enter city or town name:")
        if place_name:
            results = geocode_place(place_name)
            if results:
                options = {}
                for r in results:
                    admin = r.get("admin1", "")
                    country = r.get("country", "")
                    label = f"{r.get('name', '')}"
                    if admin:
                        label += f", {admin}"
                    if country:
                        label += f", {country}"
                    label = f"{label} (Lat: {r['latitude']:.2f}, Lon: {r['longitude']:.2f})"
                    options[label] = (r["latitude"], r["longitude"])

                selected_label = st.selectbox("Select the correct match:", list(options.keys()), key=f"sel_{key_suffix}")
                user_lat, user_lon = options[selected_label]
                st.success(f"Location set: Lat {user_lat:.4f}, Lon {user_lon:.4f}")
            else:
                st.error("Could not find this place.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            user_lat = st.number_input(lat_label, value=default_lat, format="%.4f")
        with col2:
            user_lon = st.number_input(lon_label, value=default_lon, format="%.4f")
    return user_lat, user_lon


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
        st.info("Upload a SAWS Excel file, or fill in the daily or monthly template for rainfall from any other source. Rainfall gauge data with pre-computed precipitation thresholds (Smith, 2023). Rainfall gauges SPI up to date to 2021 rainfall data.")

    with col2:
        if st.button("No — Use CHIRPS Satellite Data", use_container_width=True):
            st.session_state["path"] = "chirps"
            st.rerun()
        st.info("No file needed — just enter your coordinates. Up-to-date data to 2026. Note: CHIRPS satellite data often tends to overestimate low amounts of rainfall and underestimate high amounts of rainfall.")

# ---------- Rainfall upload path (SAWS, daily template, monthly template) ----------
elif st.session_state["path"] == "upload":

    if st.button("Start Over", on_click=reset_app):
        pass

    st.title("Drought Tracker: Upload Rainfall Data")
    st.markdown("### Notice: This application uses your 12-month cumulative rainfall to check for drought conditions based on pre-computed precipitation thresholds (Smith, 2023).")

    st.markdown("#### Step 1: Enter your location")
    user_lat, user_lon = location_inputs("2a", 0.0, 0.0, "Enter Latitude (e.g., -33.8000)", "Enter Longitude (e.g., 19.8000)")

    # --- Map check for the location entered in Step 1 ---
    show_location_map(user_lat, user_lon)

    st.markdown("#### Step 2: Upload Rainfall Data")
    st.markdown("A minimum of 12 months of data is required.")
    file_type = st.radio("What kind of file do you have?", [FILE_SAWS, FILE_DAILY, FILE_MONTHLY], key="file_type")

    if file_type == FILE_SAWS:
        st.markdown("Upload your South African Weather Service (SAWS) daily rainfall Excel file as you received it.")

    elif file_type == FILE_DAILY:
        st.markdown("For daily rainfall from any other source. Download the template, fill in the **Data** sheet, then upload it.")
        template_download_button("Daily_Rainfall_Template.xlsx", "Download daily template")
        st.table(pd.DataFrame({
            "Date": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "Rainfall_mm": ["0", "12.4", "-99"]
        }))
        st.caption("0 = no rain. -99 = missing (no reading taken).")

    else:
        st.markdown("For monthly totals from any other source. Download the template, fill in the **Data** sheet, then upload it. Only enter months that were measured in full.")
        template_download_button("Monthly_Rainfall_Template.xlsx", "Download monthly template")
        st.table(pd.DataFrame({
            "Year": ["2024", "2024", "2024"],
            "Month": ["1", "2", "3"],
            "Rainfall_mm": ["45.2", "0", "-99"]
        }))
        st.caption("0 = no rain. -99 = missing month.")

    # A separate uploader per file type, so switching type clears the previous file
    uploaded_file = st.file_uploader("Upload your Excel file (.xlsx, .xls)", type=["xlsx", "xls"], key=f"uploader_{file_type}")

    if uploaded_file is not None:
        template_msgs_shown = False
        try:
            # ---------- Route A: SAWS daily export ----------
            if file_type == FILE_SAWS:
                rain_data = read_saws_excel(uploaded_file)

                # Location check: show the result, and ask if the file disagrees
                file_lat, file_lon, _ = read_station_info(rain_data)
                _, _, _, loc_msgs = resolve_location(user_lat, user_lon, file_lat, file_lon)
                show(loc_msgs)
                use_file_coords = True
                if location_mismatch(user_lat, user_lon, file_lat, file_lon):
                    use_file_coords = st.checkbox("Use the file's station coordinates instead", value=True)

                # Map check again if the file changed the location that will be used
                used_lat, used_lon, _, _ = resolve_location(user_lat, user_lon, file_lat, file_lon, use_file_coords)
                if (used_lat, used_lon) != (user_lat, user_lon):
                    st.markdown("**Location that will be used for the thresholds:**")
                    show_location_map(used_lat, used_lon)

                prepared = prepare_saws(rain_data, user_lat, user_lon, use_file_coords)

            # ---------- Route B: daily template ----------
            elif file_type == FILE_DAILY:
                listed_days, template_msgs = read_daily_template(uploaded_file)
                show(template_msgs)
                template_msgs_shown = True

                last_date = listed_days.index.max()
                record_end = st.date_input("My record runs up to:", value=last_date.date(), min_value=last_date.date())
                zero_fill = st.checkbox("Blank or unlisted days had no rain")

                prepared = prepare_daily(None, record_end, zero_fill, user_lat, user_lon, listed=(listed_days, template_msgs))

            # ---------- Route C: monthly template ----------
            else:
                prepared = prepare_monthly(uploaded_file, user_lat, user_lon)
                show(prepared["messages"], sections=("template",))

        except AnalysisError as e:
            # Daily template messages are already on screen by the time prepare_daily runs
            if template_msgs_shown:
                e.messages = [m for m in e.messages if m["section"] != "template"]
            stop_with(e)

        show(prepared["messages"], sections=("quality", "monthly"))

        monthly_stats = prepared["monthly"]
        st.markdown("### Your Cumulative Rainfall Results")
        st.dataframe(monthly_stats[["Total_Monthly_Rain", "Rolling_12_Month_Rainfall"]])
        show(prepared["messages"], sections=("reminder",))

        st.markdown("---")
        st.markdown("### Step 3: Check Against Thresholds")
        st.markdown("Extract the expected 12-month precipitation threshold for your location based on Smith's (2023) interpolated raster data.")

        if st.button("Check Drought Status", type="primary"):
            try:
                result = evaluate_rainfall(prepared)
            except AnalysisError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"An error occurred while reading the spatial data: {e}")
            else:
                show(result["messages"], sections=("thresholds",))

                st.markdown("#### Historical 12-Month Rainfall vs. Thresholds")
                chart_data = monthly_stats[["Rolling_12_Month_Rainfall"]].copy()
                chart_data["Normal Threshold (SPI=0)"] = result["thresholds"]["normal"]
                chart_data["Drought Threshold (SPI=-1)"] = result["thresholds"]["drought"]
                st.line_chart(chart_data)

                show(result["messages"], sections=("status",))

# ---------- CHIRPS satellite path ----------
elif st.session_state["path"] == "chirps":

    if st.button("Start Over", on_click=reset_app):
        pass

    st.title("CHIRPS Drought Tracker")
    st.markdown("### Notice: This application uses CHIRPS satellite rainfall data to calculate SPI-12 at any location in South Africa.")
    st.markdown("No rainfall file upload is needed. Just enter your coordinates.")

    st.markdown("#### Enter your location")
    user_lat, user_lon = location_inputs("2b", -33.7609, 19.4741, "Latitude (e.g., -33.7609)", "Longitude (e.g., 19.4741)")

    # --- Map check for the chosen location ---
    show_location_map(user_lat, user_lon)

    if st.button("Run SPI Calculation", type="primary"):
        try:
            result = analyse_chirps(user_lat, user_lon)
        except AnalysisError as e:
            st.error(str(e))
            st.stop()

        monthly_df = result["monthly"]
        show(result["messages"], sections=("data", "thresholds"))

        st.markdown("### CHIRPS SPI-12 Results (Last 24 Months)")
        st.dataframe(monthly_df.tail(24))
        st.download_button(
            label="Download Full SPI-12 Results (CSV)",
            data=monthly_df.to_csv(),
            file_name="CHIRPS_SPI12_Results.csv",
            mime="text/csv",
        )
        st.markdown("---")

        if result["status"] is None:
            show(result["messages"], sections=("status",))
            st.stop()

        st.markdown("#### Historical 12-Month Rainfall vs. Averaged Thresholds")
        chart_data = monthly_df[["Rolling_12_Month_Rainfall"]].copy()
        chart_data["Normal (SPI=0 Average)"] = result["thresholds"]["normal"]
        chart_data["Drought (SPI=-1 Average)"] = result["thresholds"]["drought"]
        st.line_chart(chart_data)

        st.markdown("#### Historical SPI-12")
        spi_chart = monthly_df[["SPI_12"]].copy()
        spi_chart["SPI = 0 (Normal)"] = 0.0
        spi_chart["SPI = -1 (Drought)"] = -1.0
        st.line_chart(spi_chart)

        show(result["messages"], sections=("status",))
