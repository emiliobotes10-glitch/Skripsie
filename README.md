# Drought Tracker (Skripsie)

A tool that tells a user in South Africa whether their location is in a drought, using
12-month rainfall and the Standardised Precipitation Index (SPI-12). It runs as a
website and as an Android app, and both give the same results.

| | Link |
|---|---|
| Website | https://skripsie-pjm65fzu4xfregcj8qvund.streamlit.app |
| Android app (.apk) | https://github.com/emiliobotes10-glitch/Skripsie/releases/latest/download/drought-tracker.apk |
| Backend for the app | https://skripsie-23pz.onrender.com (check: `/health`) |

## What it does

The user chooses one of two paths.

**1. Upload rainfall data.** For users with at least 12 months of rain-gauge data.
Three file types are accepted:

- a SAWS (South African Weather Service) daily export, as received;
- the daily rainfall template (`Daily_Rainfall_Template.xlsx`);
- the monthly rainfall template (`Monthly_Rainfall_Template.xlsx`).

The tool checks data quality, builds monthly totals and 12-month rolling sums, and
compares the latest 12-month total with the precipitation thresholds of Smith (2023)
for SPI = 0 (normal) and SPI = -1 (drought) at the user's location.

**2. CHIRPS satellite data.** For users with no rainfall record. The tool reads the
CHIRPS v3 monthly rainfall for the nearest grid cell (January 1981 onward), fits a
gamma distribution per calendar month, and calculates SPI-12.

Both paths report a status and, where relevant, how long the deficit has lasted:

| Status | Meaning |
|---|---|
| Safe | At or above normal |
| Dry Spell | Below normal, with no recent drought |
| Recovering | Below normal after a drought; still part of the drought event |
| Drought | Below the drought threshold (CHIRPS also gives moderate, severe or extreme) |
| Uncertain | Below normal, but a data gap or a short record prevents classification |

### Data-quality rules for uploaded rainfall

- More than 15% missing data: the file is rejected.
- 10 to 15% missing: accepted with a warning.
- A month with 11 or more missing days, or 5 or more consecutive missing days, is
  treated as missing. Fewer missing days are filled in proportion (WMO-based rule).
- An incomplete final month is left out of the analysis.

## How the system fits together

```
                 GitHub repository (this one)
                 code + data files, updated daily by a workflow
                    |                          |
        Streamlit Community Cloud           Render
        runs combined_tracker_v0.py         runs api/main.py + core/
        (calculations and screens)          (calculations only)
                    |                          |
                 Website                   Android app
                                           (screens only; built with Flutter)
```

- The **website** does its calculations and draws its screens in one script.
- The **Android app** only draws screens. It sends the location or file to the backend
  on Render, which runs the calculations and returns the result.
- Both servers deploy from this repository, so both pick up new CHIRPS months
  automatically.

## Files in this repository

| File or folder | Purpose |
|---|---|
| `combined_tracker_v0.py` | The website (Streamlit). This is the file the live site runs. |
| `core/` | The same calculations as plain Python functions, with no Streamlit, used by the backend |
| `api/main.py` | The backend for the Android app (FastAPI) |
| `app.py` | An alternative website script that uses `core/`. Not currently deployed. |
| `SPI12_0.tif`, `SPI12_NEG1.tif` | Smith (2023) threshold rasters for SPI = 0 and SPI = -1 |
| `chirps_sa_monthly.nc` | CHIRPS monthly rainfall for South Africa, the fixed history |
| `chirps_sa_recent.nc` | Months added since the history was built. Created by the first automatic update. |
| `update_chirps.py` | Downloads and clips new CHIRPS months |
| `.github/workflows/update-chirps.yml` | Runs `update_chirps.py` every day |
| `Daily_Rainfall_Template.xlsx`, `Monthly_Rainfall_Template.xlsx` | Templates users fill in |
| `requirements.txt` | Python packages, used by both Streamlit and Render |
| `chirps_spi_app.py`, `drought_tracker_app.py` | Earlier versions, kept for reference |

The Android app's source code (Flutter) is not in this repository.

### Two copies of the calculations

`combined_tracker_v0.py` (website) and `core/` (app backend) contain the same
calculations. `core/` was produced from the website script and checked against it:
on 53 test cases using the real threshold rasters and CHIRPS data, both produced
identical messages, tables and results. A change to the method must be made in both
places, or the website and the app will disagree.

## Automatic CHIRPS updates

A GitHub Actions workflow runs every day at about 06:17 South African time. When the
Climate Hazards Center has published a new month, the workflow clips it to South
Africa, adds it to `chirps_sa_recent.nc` and commits the file. Streamlit and Render
then redeploy with the new month. On days with nothing new, nothing changes.

## Running it locally

```
pip install -r requirements.txt

streamlit run combined_tracker_v0.py        # the website
uvicorn api.main:app --reload               # the backend; test page at http://127.0.0.1:8000/docs
```

### Backend endpoints

- `GET /health` returns `{"ok": true}`
- `POST /chirps` with JSON `{"lat": -33.76, "lon": 19.47}`
- `POST /rainfall` with form fields `file`, `file_type` (`saws`, `daily` or `monthly`),
  `lat`, `lon`, and for the daily template `record_end` (yyyy-mm-dd) and `zero_fill`
- `GET /templates/daily` and `GET /templates/monthly` download the empty templates

## Installing the Android app

Download the `.apk` from the link at the top, open it, and allow the browser to install
apps when Android asks. The app is not on the Google Play Store. It needs an internet
connection, because the calculations run on the backend.

## Limitations

- Valid only for locations inside South Africa (latitude -35 to -22, longitude 16 to 33).
- CHIRPS tends to overestimate low rainfall and underestimate high rainfall.
- The rain-gauge thresholds are based on rainfall data up to 2021.
- The free hosting tiers put the servers to sleep when idle, so the first request
  after a quiet period can take up to a minute.
- The automatic update depends on the CHIRPS file location and naming staying the same.
- Android only. iPhone users can use the website.

## Reference

Precipitation thresholds: Smith (2023). CHIRPS v3: Climate Hazards Center, University
of California, Santa Barbara.
