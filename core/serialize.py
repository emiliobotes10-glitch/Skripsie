"""Turn an analysis result into plain JSON (no NaN, no Timestamps)."""

import datetime
import math

import numpy as np
import pandas as pd


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime.datetime)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def monthly_to_series(monthly):
    rows = []
    for month, row in monthly.iterrows():
        rows.append({
            "month": month.strftime("%Y-%m"),
            "monthly": row.get("Total_Monthly_Rain", row.get("Monthly_Rain")),
            "rolling_12": row.get("Rolling_12_Month_Rainfall"),
            "spi": row.get("SPI_12"),
        })
    return rows


def to_json(result):
    out = {k: v for k, v in result.items() if k != "monthly"}
    if "monthly" in result:
        out["series"] = monthly_to_series(result["monthly"])
    if out.get("latest") and out["latest"].get("month") is not None:
        out["latest"] = {**out["latest"], "month": out["latest"]["month"].strftime("%Y-%m")}
    return _clean(out)
