"""
Fetch any new CHIRPS v3 monthly rainfall and save it to chirps_sa_recent.nc.

Run by the GitHub Action in .github/workflows/update-chirps.yml, or by hand:
    python update_chirps.py

chirps_sa_monthly.nc (the full history) is only read. For each month after the
last one already held, the script downloads the Africa GeoTIFF from CHC, cuts
out the cells matching the history grid, keeps the same outside-South-Africa
cells as the history (so no shapefile is needed) and adds the month to the
small chirps_sa_recent.nc. It stops at the first month CHC has not published.
"""
import os
import sys
import tempfile

import numpy as np
import pandas as pd
import rasterio
import requests
import xarray as xr

NC_PATH = "chirps_sa_monthly.nc"       # full history, never rewritten
RECENT_PATH = "chirps_sa_recent.nc"    # small file holding the months added since
VAR = "rainfall"
URL = ("https://data.chc.ucsb.edu/products/CHIRPS/v3.0/monthly/africa/tifs/"
       "chirps-v3.0.{year}.{month:02d}.tif")


def download_tif(year, month, folder):
    """Return the local path of the month's GeoTIFF, or None if not published yet."""
    url = URL.format(year=year, month=month)
    r = requests.get(url, stream=True, timeout=120)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    path = os.path.join(folder, os.path.basename(url))
    with open(path, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return path


def read_on_grid(tif_path, lats, lons):
    """Read the GeoTIFF values at the cell centres of the existing grid."""
    with rasterio.open(tif_path) as src:
        band = src.read(1).astype("float32")
        if src.nodata is not None:
            band[band == src.nodata] = np.nan
        band[band < 0] = np.nan  # CHIRPS uses -9999 for no data
        rows, _ = rasterio.transform.rowcol(src.transform, np.full(len(lats), lons[0]), lats)
        _, cols = rasterio.transform.rowcol(src.transform, lons, np.full(len(lons), lats[0]))
        rows, cols = np.asarray(rows), np.asarray(cols)
        if rows.min() < 0 or cols.min() < 0 or rows.max() >= src.height or cols.max() >= src.width:
            raise ValueError("The existing grid falls outside the downloaded GeoTIFF.")
        # Guard against a grid that does not line up with CHIRPS cells
        xs, _ = rasterio.transform.xy(src.transform, np.zeros(len(cols), int), cols)
        _, ys = rasterio.transform.xy(src.transform, rows, np.zeros(len(rows), int))
        if np.abs(np.asarray(xs) - lons).max() > 0.026 or np.abs(np.asarray(ys) - lats).max() > 0.026:
            raise ValueError("The existing grid does not line up with the CHIRPS 0.05 degree grid.")
        return band[np.ix_(rows, cols)]


def next_month(ts):
    """First timestamp of the following month, keeping the file's day convention."""
    nxt = ts + pd.DateOffset(months=1)
    if ts.is_month_end:
        nxt = nxt + pd.offsets.MonthEnd(0)
    return nxt


def main():
    # The big history file is only read, never rewritten, so the repo stays small.
    with xr.open_dataset(NC_PATH) as ds:
        da = ds[VAR].transpose("time", "latitude", "longitude").load()
    lats = da["latitude"].values.astype("float64")
    lons = da["longitude"].values.astype("float64")
    # Cells that are blank or 0 in every month are outside the South Africa clip
    outside = (da.isnull() | (da == 0)).all("time").values
    outside_fill = da.values[0][outside]

    recent = None
    if os.path.exists(RECENT_PATH):
        with xr.open_dataset(RECENT_PATH) as ds:
            recent = ds[VAR].transpose("time", "latitude", "longitude").load()

    last = pd.Timestamp(da["time"].values.max())
    if recent is not None and recent.sizes["time"]:
        last = max(last, pd.Timestamp(recent["time"].values.max()))
    today = pd.Timestamp.now(tz="UTC").tz_localize(None)
    new_times, new_data = [], []

    with tempfile.TemporaryDirectory() as tmp:
        t = next_month(last)
        while (t.year, t.month) < (today.year, today.month):
            tif = download_tif(t.year, t.month, tmp)
            if tif is None:
                print(f"{t:%Y-%m} is not published yet.")
                break
            grid = read_on_grid(tif, lats, lons)
            grid[outside] = outside_fill
            new_times.append(t)
            new_data.append(grid)
            print(f"Added {t:%Y-%m}")
            os.remove(tif)
            t = next_month(t)

    if not new_times:
        print(f"Nothing to add. Data already runs to {last:%Y-%m}.")
        return 0

    addition = xr.DataArray(
        np.stack(new_data).astype("float32"),
        dims=("time", "latitude", "longitude"),
        coords={"time": pd.DatetimeIndex(new_times), "latitude": da["latitude"], "longitude": da["longitude"]},
        name=VAR,
    )
    if recent is not None:
        addition = xr.concat([recent, addition], dim="time")

    tmp_path = RECENT_PATH + ".tmp"
    addition.to_dataset(name=VAR).to_netcdf(tmp_path, encoding={VAR: {"zlib": True, "complevel": 5}})
    os.replace(tmp_path, RECENT_PATH)  # only overwrite once the new file is complete
    print(f"Saved {RECENT_PATH}: data now runs to {new_times[-1]:%Y-%m} "
          f"({addition.sizes['time']} months in the recent file).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
