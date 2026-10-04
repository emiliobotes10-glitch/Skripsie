"""Drought Tracker calculations, shared by the Streamlit app and the API.

Nothing in this package imports Streamlit. Functions return values and a list of
messages ({"level", "text", "section"}) instead of drawing anything on screen.
"""

SA_LAT_RANGE = (-35.0, -22.0)
SA_LON_RANGE = (16.0, 33.0)


class AnalysisError(ValueError):
    """Raised when an analysis cannot continue (the old st.stop()).

    `messages` holds anything collected before the failure, so the caller can
    still show earlier warnings (e.g. a location mismatch) next to the error.
    """

    def __init__(self, text, messages=None):
        super().__init__(text)
        self.messages = list(messages or [])


def msg(level, text, section):
    """level: info | success | warning | error | write"""
    return {"level": level, "text": text, "section": section}


def in_south_africa(lat, lon):
    return (SA_LAT_RANGE[0] <= lat <= SA_LAT_RANGE[1]
            and SA_LON_RANGE[0] <= lon <= SA_LON_RANGE[1])
