"""Smith (2023) 12-month precipitation thresholds, sampled from the rasters."""

from pathlib import Path

import rasterio

from . import AnalysisError, in_south_africa

DATA_DIR = Path(__file__).resolve().parent.parent
NORMAL_TIF = DATA_DIR / "SPI12_0.tif"
DROUGHT_TIF = DATA_DIR / "SPI12_NEG1.tif"


def get_saws_thresholds(lat, lon, normal_path=NORMAL_TIF, drought_path=DROUGHT_TIF):
    """Return (normal, drought) in mm for SPI = 0 and SPI = -1 at this point."""
    if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
        raise AnalysisError("Please enter a valid Latitude and Longitude in Step 1.")
    if not in_south_africa(lat, lon):
        raise AnalysisError("Coordinates are outside South Africa bounds (-35 to -22 lat, 16 to 33 lon).")

    try:
        with rasterio.open(normal_path) as ds_norm, rasterio.open(drought_path) as ds_drought:
            normal = float(next(ds_norm.sample([(lon, lat)]))[0])
            drought = float(next(ds_drought.sample([(lon, lat)]))[0])
    except (FileNotFoundError, rasterio.errors.RasterioIOError):
        raise AnalysisError("Threshold raster files not found.")

    if normal < 0 or drought < 0:
        raise AnalysisError(
            "Error: The coordinates provided returned an invalid value. "
            "Make sure your coordinates are within South Africa."
        )
    return normal, drought
