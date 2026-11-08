"""Names for the IDs found in Edge activity-profile files.

Every entry here was observed on a real Edge 1040 profile file (checked against what the device
shows) or comes from the data-field table in Activity Profile Editor's FIT_PATCH.md
(https://github.com/fullcarbonbike/Activity-Profile-Editor, MIT). Unknown IDs print as numbers;
add names here when you confirm one.
"""

# Message 14 (data screen), field 7: data-field type IDs.
DATA_FIELDS = {
    3: "Cadence",
    6: "Distance",
    48: "Speed",
    56: "Timer",
    343: "Heart Rate Graph",
    346: "Power Graph",
    511: "Workout Comparison",
    522: "Duration",
    65535: "(empty)",
}

# Message 14, field 10: which kind of screen the record is.
SCREEN_TYPES = {
    25: "Map",
    38: "Workout",
    104: "ClimbPro",
}

# Message numbers seen in Edge sport-profile files.
MESSAGES = {
    0: "file_id",
    14: "data screen",
    16: "recurring alert",
}


def field_name(fid: int) -> str:
    return DATA_FIELDS.get(fid, str(fid))


def field_id(token: str) -> int:
    token = token.strip()
    if token.isdigit():
        return int(token)
    lookup = {v.lower(): k for k, v in DATA_FIELDS.items()}
    if token.lower() in ("none", "empty"):
        return 65535
    if token.lower() not in lookup:
        raise KeyError(f"unknown data field {token!r}; use its numeric ID")
    return lookup[token.lower()]
