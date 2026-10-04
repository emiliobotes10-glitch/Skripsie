"""Drought Tracker API for the phone app.

Run locally:  uvicorn api.main:app --reload
Test page:    http://127.0.0.1:8000/docs
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from core import AnalysisError
from core.chirps import analyse_chirps
from core.rainfall import FILE_TYPES, analyse_rainfall
from core.serialize import to_json

MAX_UPLOAD_BYTES = 5_000_000
ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = {
    "daily": "Daily_Rainfall_Template.xlsx",
    "monthly": "Monthly_Rainfall_Template.xlsx",
}
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

app = FastAPI(title="Drought Tracker API")


def error_response(status_code, detail, messages=None):
    # Always JSON with "detail", so the app can show the reason instead of crashing.
    return JSONResponse(status_code=status_code, content={"detail": detail, "messages": messages or []})


@app.get("/health")
def health():
    return {"ok": True}


class Location(BaseModel):
    lat: float
    lon: float


@app.post("/chirps")
def chirps(loc: Location):
    try:
        return to_json(analyse_chirps(loc.lat, loc.lon))
    except AnalysisError as e:
        return error_response(400, str(e), e.messages)
    except Exception as e:
        return error_response(500, f"Something went wrong on the server: {e}")


@app.post("/rainfall")
def rainfall(
    file: UploadFile = File(...),
    file_type: str = Form("saws"),
    lat: Optional[float] = Form(None),
    lon: Optional[float] = Form(None),
    use_file_coords: bool = Form(True),
    record_end: Optional[str] = Form(None),
    zero_fill: bool = Form(False),
):
    """Upload a rainfall Excel file.

    file_type: saws | daily | monthly.
    lat/lon: needed for the templates; optional for SAWS files (the file has
        the station's coordinates). If a SAWS reply has location.mismatch =
        true, the app can ask the user and send again with use_file_coords = false.
    record_end, zero_fill: daily template only. record_end is yyyy-mm-dd and
        defaults to the last date in the file.
    """
    if file_type not in FILE_TYPES:
        return error_response(400, f"Unknown file type '{file_type}'.")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        return error_response(413, "File too large (max 5 MB).")
    try:
        return to_json(analyse_rainfall(data, file_type, lat, lon, use_file_coords, record_end or None, zero_fill))
    except AnalysisError as e:
        return error_response(400, str(e), e.messages)
    except Exception as e:
        return error_response(400, f"Could not read this file. Is it the right kind of Excel file? ({e})")


@app.get("/templates/{kind}")
def template(kind: str):
    """Download the empty daily or monthly rainfall template."""
    name = TEMPLATES.get(kind)
    if name is None or not (ROOT / name).exists():
        return error_response(404, "Template not found.")
    return FileResponse(ROOT / name, media_type=XLSX_MIME, filename=name)
