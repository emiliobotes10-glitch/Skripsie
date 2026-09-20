import streamlit as st
import pandas as pd
import numpy as np
import datetime


# ==========================================
# PHASE 1: APP SETUP & USER INTERFACE
# ==========================================
st.set_page_config(page_title="Drought Tracker", layout="centered")
st.title("Drought Tracker: Are You In A Drought?")

# Updated Notice: Accurate representation of the application's math
st.markdown("### ⚠️ Notice: This application uses your 12-month cumulative rainfall to check for drought conditions based on pre-computed precipitation thresholds (Smith, 2023).")

# Ask the user to enter their coordinates using number input boxes.
# Note: These coordinates will be used to look up the precipitation threshold from Smith's (2023) interpolated raster in a future phase.
st.markdown("#### Step 1: Enter your location")
col1, col2 = st.columns(2)
with col1:
    user_lat = st.number_input("Enter Latitude (e.g., -33.8000)", value=0.0, format="%.4f")
with col2:
    user_lon = st.number_input("Enter Longitude (e.g., 19.8000)", value=0.0, format="%.4f")

# Create a file uploader restricted specifically to Excel files
st.markdown("#### Step 2: Upload SAWS Data")
st.markdown("Please upload your historical South African Weather Service (SAWS) rainfall data below. A minimum of 12 months of data is required.")
uploaded_file = st.file_uploader("Upload your SAWS Excel file (.xlsx, .xls)", type=['xlsx', 'xls'])


# ==========================================
# PHASE 2: INGESTION & TIERED MISSING DATA CHECK
# ==========================================
# The app will only execute the code below if the user has actually uploaded a file.
if uploaded_file is not None:
    st.info("File uploaded successfully. Scanning data quality...")
    
    # Load the uploaded file from memory into a pandas table
    rain_data = pd.read_excel(uploaded_file)
    
    # Initialize our counters and lists
    cell_Count = 0
    value_Count = 0
    current_year = 0
    has_warning = False # This flag tracks if data is in the 10-15% warning tier
    
    # Define exactly what SAWS considers "missing" data based on the legend.
    missing_flags = ["***", "----", "A", "B", "---", "="]
    
    # Run the row-by-row scanning logic to check data health
    for index, row in rain_data.iterrows():
        first_col_value = str(row['Unnamed: 0'])
        
        # --- Find the Year ---
        if "Daily Rain" in first_col_value:
            words = first_col_value.split()
            for word in words:
                if word.isdigit() and len(word) == 4:
                    current_year = int(word)
                    break 

        # --- Find the Grid ---
        if first_col_value.isdigit() and 1 <= int(first_col_value) <= 31:
            current_day = int(first_col_value)
            
            month_columns = [
                (1, 'Unnamed: 1'), (2, 'Unnamed: 2'), (3, 'Unnamed: 3'),
                (4, 'Unnamed: 4'), (5, 'Unnamed: 5'), (6, 'Unnamed: 6'),
                (7, 'Unnamed: 7'), (8, 'Unnamed: 8'), (9, 'Unnamed: 9'),
                (10, 'Unnamed: 10'), (11, 'Unnamed: 11'), (12, 'Unnamed: 12')
            ]
            
            for current_month, column_name in month_columns:
                
                # --- Verify the Date ---
                try:
                    # Skip impossible dates like Feb 30 to prevent crashes
                    actual_date = datetime.date(current_year, current_month, current_day)
                    cell_Count = cell_Count + 1
                except ValueError:
                    continue 

                # --- Check the Data Health ---
                cell_data = row[column_name]
                
                if pd.isna(cell_data) or str(cell_data).strip() == "":
                    value_Count = value_Count + 1
                else:
                    text_data = str(cell_data).strip()
                    if text_data in missing_flags:
                        # Do not count as a valid value
                        pass
                    elif 'C' in text_data or 'E' in text_data:
                        value_Count = value_Count + 1
                    else:
                        try:
                            float(text_data)
                            value_Count = value_Count + 1
                        except ValueError:
                            pass


    # --- The Tiered Missing Data Check (Lo Presti et al., 2015 via Smith, 2023) ---
    if cell_Count == 0:
        st.error("Error: 0 valid calendar days were processed. Check file formatting.")
        st.stop() # Halt the app
    
    missing_Count = cell_Count - value_Count
    percentage_missing = (missing_Count / cell_Count) * 100
    
    st.write(f"**Data Quality Scan:** {percentage_missing:.2f}% of data is marked as missing.")
    
    if percentage_missing > 15.0:
        st.error(f"❌ Data rejected. Your percentage of missing data ({percentage_missing:.2f}%) is > 15%. Cannot yield accurate results.")
        st.stop() # Halt the app immediately
        
    elif 10.0 <= percentage_missing <= 15.0:
        st.warning(f"⚠️ Warning: Missing data is between 10-15%. Proceeding, but results may be less reliable.")
        has_warning = True # We carry this flag forward to the final result
        
    else:
        st.success("✅ Data quality is excellent (< 10% missing). Proceeding to aggregation...")


    # ==========================================
    # PHASE 3: DATA CLEANING & AGGREGATION
    # ==========================================
    st.info("Cleaning daily values and aggregating to monthly totals...")
    
    clean_dates = []
    clean_rainfall = []
    
    # Run the loop again to extract actual numbers
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
                        # DELIBERATE CHOICE: Missing days are treated as zero rainfall. 
                        # With overall missing data capped at 15%, this introduces a small, acceptable 
                        # conservative bias (slightly underestimates total rainfall) rather than failing.
                        clean_rainfall.append(0.0)
                        
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

    # Reconstruct the daily data table
    daily_df = pd.DataFrame({
        'Date': pd.to_datetime(clean_dates),
        'Rainfall_mm': clean_rainfall
    })
    

    # Simplified Monthly Aggregation (No 70% Rule)
    monthly_stats = daily_df.groupby(pd.Grouper(key='Date', freq='ME')).agg(
        Total_Monthly_Rain=('Rainfall_mm', 'sum')
    ).reset_index()
    
    monthly_stats = monthly_stats.rename(columns={'Date': 'Month_Date'})
    monthly_stats = monthly_stats.set_index('Month_Date')

    # ==========================================
    # PHASE 4: THE 12-MONTH ROLLING SUM
    # ==========================================
    total_months = len(monthly_stats)
    if total_months < 12:
        st.error(f"❌ Insufficient data. You only have {total_months} months of data. Exactly 12 months minimum required.")
        st.stop()
    
    st.info("Calculating 12-Month Cumulative Rainfall...")
    
    # Note: Because this requires 12 preceding months, the first 11 rows of this calculation 
    # will mathematically result in 'NaN'. The valid rolling sum begins from row 12 onward.
    timescale = 12
    monthly_stats['Rolling_12_Month_Rainfall'] = monthly_stats['Total_Monthly_Rain'].rolling(window=timescale, min_periods=timescale).sum()


    st.markdown("### 📊 Your Cumulative Rainfall Results")
    
    # Display the calculated table
    st.dataframe(monthly_stats[['Total_Monthly_Rain', 'Rolling_12_Month_Rainfall']])
    
    # Persistent Warning check
    if has_warning:
        st.warning("⚠️ **Reminder:** Due to the missing data percentage (10-15%) in your upload, this final cumulative sum may be slightly underestimated.")