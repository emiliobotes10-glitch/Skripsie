# Drought Tracker

This repository holds the code and data for my research project. The project is an application that lets a user anywhere in South Africa check whether their location is in a drought, using rainfall.

The application runs as a website at https://skripsie-pjm65fzu4xfregcj8qvund.streamlit.app

An Android version can be downloaded from https://github.com/emiliobotes10-glitch/Skripsie/releases/latest/download/drought-tracker.apk

## What the application does

The user starts by choosing one of two options.

The first option is for users who have at least 12 months of rainfall data. They upload a daily rainfall file from the South African Weather Service (SAWS), or they fill in one of the two templates in this repository. The application checks how much of the data is missing. It then adds up the rainfall for each month and for each 12 month period. The latest 12 month total is compared with two rainfall thresholds for the user's location, which come from Smith (2023). The first threshold is the rainfall at SPI = 0, which is treated as normal. The second is the rainfall at SPI = -1, which is treated as the start of a drought.

The second option is for users who have no rainfall data. The application uses CHIRPS satellite rainfall for the user's location, which starts in January 1981. It fits a gamma distribution to the rainfall record and calculates SPI-12 for each month.

Both options give one of five results. Safe means the rainfall is normal or above normal. Dry Spell means the rainfall is below normal, but there has been no drought recently. Drought means the rainfall is below the drought threshold. Recovering means the rainfall has risen above the drought threshold after a drought, but is still below normal. Uncertain means the rainfall is below normal, but missing data or a short record makes it unclear which of these applies.

If the result is Drought or Recovering, the application also reports how many months the rainfall has been below normal.

## Missing data

A rainfall file is rejected if more than 15% of its days are missing. A warning is shown if between 10% and 15% are missing.

A month is treated as missing if it has 11 or more missing days, or 5 or more missing days in a row. If a month has fewer missing days than that, its total is scaled up to cover them. A final month that is not complete is left out.

## Files

The calculations described in the report are in `combined_tracker_v0.py`. Comments in that file mark each step.

| File | What it is |
|---|---|
| `combined_tracker_v0.py` | The website, including all the calculations |
| `SPI12_0.tif` and `SPI12_NEG1.tif` | The rainfall thresholds from Smith (2023) for SPI = 0 and SPI = -1 |
| `chirps_sa_monthly.nc` | CHIRPS monthly rainfall for South Africa from January 1981 |
| `chirps_sa_recent.nc` | CHIRPS months added after the file above was built. This file appears after the first update. |
| `update_chirps.py` | Adds new CHIRPS months when they are published |
| `Daily_Rainfall_Template.xlsx` and `Monthly_Rainfall_Template.xlsx` | Templates that users fill in with their own rainfall |
| `core` and `api` | The same calculations, set up for the Android app |
| `app.py` | A second version of the website that uses the `core` folder. It is not in use. |
| `chirps_spi_app.py` and `drought_tracker_app.py` | Earlier versions of the application |
| `requirements.txt` | The Python packages the application needs |

## Keeping the CHIRPS rainfall up to date

A script checks every day whether a new month of CHIRPS rainfall has been published. When a new month is available, it is added to this repository. The website and the Android app then use it without any further work.

## The website and the Android app

The website and the Android app use the same calculations. The calculations exist in two places, because the app cannot run the website's code directly. The website uses `combined_tracker_v0.py` and the app uses the `core` folder. A change to the method has to be made in both places.

The Android app is not on the Google Play Store. To install it, download the file from the link above and open it on an Android phone. The phone will ask for permission to install it. The app needs an internet connection to work.

## Limitations

The application only works for locations inside South Africa. The thresholds from Smith (2023) are based on rainfall data up to 2021. CHIRPS tends to overestimate low rainfall and underestimate high rainfall. The website and the app can be slow to respond when they have not been used for a while.
