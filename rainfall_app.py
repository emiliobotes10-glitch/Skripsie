import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta

st.set_page_config(page_title="Monthly Rainfall", page_icon="🌧️", layout="centered")

st.title("🌧️ Monthly Rainfall Data")
st.markdown("Fetch 12 months of monthly rainfall for any location using the [Open-Meteo API](https://open-meteo.com/).")

# --- Location input ---
st.subheader("Location")

col1, col2 = st.columns(2)
with col1:
    location_name = st.text_input("Search by place name", placeholder="e.g. Stellenbosch")
with col2:
    st.markdown("<div style='padding-top:1.8rem; text-align:center; color:#888'>— or enter coordinates —</div>", unsafe_allow_html=True)

use_coords = st.toggle("Enter coordinates manually")

latitude, longitude, resolved_name = None, None, None

if use_coords:
    c1, c2 = st.columns(2)
    with c1:
        latitude = st.number_input("Latitude", value=-33.93, format="%.4f")
    with c2:
        longitude = st.number_input("Longitude", value=18.86, format="%.4f")
    resolved_name = f"{latitude:.2f}, {longitude:.2f}"


def geocode(place: str):
    """Use Open-Meteo geocoding to resolve a place name."""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    resp = requests.get(url, params={"name": place, "count": 5, "language": "en", "format": "json"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", [])


if not use_coords and location_name:
    results = geocode(location_name)
    if results:
        options = {
            f"{r['name']}, {r.get('admin1', '')}, {r.get('country', '')}": r
            for r in results
        }
        choice = st.selectbox("Select a match", list(options.keys()))
        picked = options[choice]
        latitude = picked["latitude"]
        longitude = picked["longitude"]
        resolved_name = choice
    else:
        st.warning("No results found. Try a different name or use coordinates.")

# --- Date range ---
st.subheader("Period")
today = date.today()
default_end = today.replace(day=1) - timedelta(days=1)  # last day of previous month
default_start = (default_end.replace(day=1) - timedelta(days=335)).replace(day=1)  # ~12 months back

c1, c2 = st.columns(2)
with c1:
    start_date = st.date_input("Start month", value=default_start, max_value=today)
with c2:
    end_date = st.date_input("End month", value=default_end, max_value=today)

# --- Fetch ---
if st.button("Get Rainfall Data", type="primary", use_container_width=True):
    if latitude is None or longitude is None:
        st.error("Please provide a location first.")
    else:
        with st.spinner("Fetching rainfall data…"):
            try:
                url = "https://archive-api.open-meteo.com/v1/archive"
                params = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": start_date.strftime("%Y-%m-%d"),
                    "end_date": end_date.strftime("%Y-%m-%d"),
                    "daily": "precipitation_sum",
                    "timezone": "auto",
                }
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                daily = data.get("daily", {})
                if not daily or not daily.get("time"):
                    st.error("No data returned for this location/period.")
                else:
                    df = pd.DataFrame({
                        "date": pd.to_datetime(daily["time"]),
                        "precipitation_mm": daily["precipitation_sum"],
                    })

                    # Aggregate to monthly totals
                    df["month"] = df["date"].dt.to_period("M")
                    monthly = df.groupby("month")["precipitation_mm"].sum().reset_index()
                    monthly.columns = ["Month", "Rainfall (mm)"]
                    monthly["Month"] = monthly["Month"].astype(str)

                    st.success(f"Showing monthly rainfall for **{resolved_name}**")

                    # Bar chart
                    st.bar_chart(monthly.set_index("Month"), y="Rainfall (mm)", color="#4A90D9")

                    # Data table
                    st.dataframe(
                        monthly.style.format({"Rainfall (mm)": "{:.1f}"}),
                        use_container_width=True,
                        hide_index=True,
                    )

                    total = monthly["Rainfall (mm)"].sum()
                    avg = monthly["Rainfall (mm)"].mean()
                    wettest = monthly.loc[monthly["Rainfall (mm)"].idxmax()]

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Total", f"{total:.0f} mm")
                    m2.metric("Monthly avg", f"{avg:.1f} mm")
                    m3.metric("Wettest month", f"{wettest['Month']}")

            except requests.RequestException as e:
                st.error(f"API request failed: {e}")
