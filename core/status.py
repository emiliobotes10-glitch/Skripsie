"""Drought status and deficit duration, shared by the SAWS and CHIRPS paths.

Both paths use the same logic with different numbers:
  - SAWS:   12-month rainfall totals (mm) against the Smith (2023) thresholds
  - CHIRPS: SPI-12 against 0 and -1

`series` is always a pandas Series in date order, ending at the latest valid
value, with NaN kept in place (gaps matter for the history checks).
"""

import pandas as pd

from . import msg

SECTION = "status"

TEXT = {
    "saws": {
        "safe": "**SAFE:** Your rainfall is above normal.",
        "drought": "**DROUGHT:** Your rainfall is below the moderate drought threshold.",
        "gap_after_normal": (
            "**UNCERTAIN HISTORY:** Your rainfall is below normal, "
            "but a data gap separates the current condition from "
            "the last normal/above-normal observation. Continuity "
            "of the dry spell cannot be confirmed."
        ),
        "dry_spell": (
            "**DRY SPELL:** You are below normal, but you have not "
            "entered a drought recently."
        ),
        "gap_after_drought": (
            "**UNCERTAIN HISTORY:** Your rainfall is below normal, "
            "but a data gap separates the current condition from "
            "the previous drought. Continuity of the recovery "
            "cannot be confirmed."
        ),
        "recovering": (
            "**RECOVERING:** You are currently out of severe drought, "
            "but have not reached full recovery (Normal). You are "
            "still in a drought event."
        ),
        "too_short": (
            "**UNCERTAIN HISTORY:** Your rainfall is below normal but "
            "your record is too short to determine whether this is a new "
            "dry spell or recovery from a prior drought."
        ),
        "pre_gap_value": "({value:.2f})",
        "no_pre_gap": "**Pre-Gap Context:** No valid rainfall value was found before the data gap.",
        "at_least": (
            "**Continuous deficit duration:** At least "
            "**{months} months**. "
            "The event began before the start of your record, so "
            "the true duration is likely longer."
        ),
    },
    "chirps": {
        "safe": "**SAFE:** Your SPI is at or above zero. No drought.",
        "drought": "**DROUGHT:** Your SPI is below -1.",
        "gap_after_normal": (
            "**CURRENT: BELOW NORMAL**\n\n"
            "Previous available SPI indicated normal "
            "or above-normal conditions, but a data gap "
            "prevents confirmation of the dry-spell history."
        ),
        "dry_spell": (
            "**DRY SPELL:** Your SPI is below normal, "
            "but you have not entered a drought recently."
        ),
        "gap_after_drought": (
            "**CURRENT: BELOW NORMAL**\n\n"
            "Previous available SPI indicated drought, "
            "but a data gap prevents confirmation of the "
            "recovery history."
        ),
        "recovering": (
            "**RECOVERING:** You are currently out of "
            "severe drought, but have not reached full "
            "recovery (SPI = 0). You are still in a "
            "drought event."
        ),
        "too_short": (
            "**UNCERTAIN HISTORY:** Your SPI is below normal "
            "but your record is too short to determine whether "
            "this is a new dry spell or recovery from a prior drought."
        ),
        "pre_gap_value": "(SPI = {value:.2f})",
        "no_pre_gap": "**Pre-Gap Context:** No valid SPI was found before the data gap.",
        "at_least": (
            "**Continuous deficit duration:** At least "
            "**{months} months**. "
            "The continuous deficit extends to the earliest "
            "valid SPI-12 value in the record."
        ),
    },
}


def spi_severity(spi):
    """Severity label for an SPI value already below -1."""
    if spi > -1.5:
        return "Moderate", "Classification: Moderate drought (SPI between -1 and -1.5)"
    if spi > -2:
        return "Severe", "Classification: Severe drought (SPI between -1.5 and -2)"
    return "Extreme", "Classification: Extreme drought (SPI below -2)"


def classify(series, normal, drought, kind):
    """Current status: Safe, Drought, Dry Spell, Recovering or Uncertain.

    Returns {"status", "severity", "messages"}.
    """
    t = TEXT[kind]
    newest_first = series.iloc[::-1]
    latest = newest_first.iloc[0]
    messages = []
    severity = None

    if latest >= normal:
        messages.append(msg("success", t["safe"], SECTION))
        return {"status": "Safe", "severity": None, "messages": messages}

    if latest < drought:
        messages.append(msg("error", t["drought"], SECTION))
        if kind == "chirps":
            severity, label = spi_severity(latest)
            messages.append(msg("write", label, SECTION))
        return {"status": "Drought", "severity": severity, "messages": messages}

    # Grey zone: below normal but not drought. Walk back to the last
    # normal or drought value to see which side we came from.
    gap_found = False
    for past in newest_first.iloc[1:]:
        if pd.isna(past):
            gap_found = True
            continue
        if past >= normal:
            if gap_found:
                messages.append(msg("warning", t["gap_after_normal"], SECTION))
                return {"status": "Uncertain", "severity": None, "messages": messages}
            messages.append(msg("warning", t["dry_spell"], SECTION))
            return {"status": "Dry Spell", "severity": None, "messages": messages}
        if past < drought:
            if gap_found:
                messages.append(msg("warning", t["gap_after_drought"], SECTION))
                return {"status": "Uncertain", "severity": None, "messages": messages}
            messages.append(msg("warning", t["recovering"], SECTION))
            return {"status": "Recovering", "severity": None, "messages": messages}

    messages.append(msg("warning", t["too_short"], SECTION))
    return {"status": "Uncertain", "severity": None, "messages": messages}


def deficit_duration(series, normal, drought, kind, pre_gap_drought_inclusive=False):
    """How long the current below-normal event has lasted.

    Walks back from the latest value, counting months below normal, until it
    reaches a normal month (found_start) or a data gap. After a gap it reports
    the first valid value before the gap.

    pre_gap_drought_inclusive: the original CHIRPS code treats a pre-gap SPI of
    exactly -1 as drought (<=); SAWS uses <. Kept as-is for now so the numbers
    match the old app; to be unified in a later change.

    Returns {"months", "found_start", "hit_gap", "gap_months", "pre_gap",
    "messages"} where pre_gap is None or {"date", "value", "class"}.
    """
    t = TEXT[kind]
    months = 0
    found_start = False
    hit_gap = False
    gap_months = 0
    pre_gap_value = None
    pre_gap_date = None

    for past_date, past in series.iloc[::-1].items():
        if pd.isna(past):
            hit_gap = True
            gap_months += 1
            continue
        if not hit_gap:
            if past < normal:
                months += 1
            else:
                found_start = True
                break
        else:
            pre_gap_value = past
            pre_gap_date = past_date
            break

    messages = []
    pre_gap = None

    if hit_gap:
        messages.append(msg("write", f"**Confirmed continuous deficit duration:** {months} months", SECTION))
        messages.append(msg("write", f"**Data gap:** {gap_months} months", SECTION))
        if pre_gap_value is not None:
            is_drought = (pre_gap_value <= drought) if pre_gap_drought_inclusive else (pre_gap_value < drought)
            if is_drought:
                cls, ctx = "Drought", "**Pre-Gap Context:** Drought."
            elif pre_gap_value >= normal:
                cls, ctx = "Normal", "**Pre-Gap Context:** Normal/Above Normal."
            else:
                cls, ctx = "Grey Zone", "**Pre-Gap Context:** Grey Zone (below normal, but not drought)."
            pre_gap = {"date": pre_gap_date, "value": float(pre_gap_value), "class": cls}
            messages.append(msg(
                "write",
                f"**Last available pre-gap observation:** {pre_gap_date.strftime('%B %Y')} "
                + t["pre_gap_value"].format(value=pre_gap_value),
                SECTION,
            ))
            messages.append(msg("write", ctx, SECTION))
        else:
            messages.append(msg("write", t["no_pre_gap"], SECTION))
    elif found_start:
        messages.append(msg(
            "write",
            f"**Continuous deficit duration:** This current deficit event has lasted for **{months} months**.",
            SECTION,
        ))
    else:
        messages.append(msg("write", t["at_least"].format(months=months), SECTION))

    return {
        "months": months,
        "found_start": found_start,
        "hit_gap": hit_gap,
        "gap_months": gap_months,
        "pre_gap": pre_gap,
        "messages": messages,
    }
