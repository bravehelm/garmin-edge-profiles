"""Named on/off settings in an Edge 1040 activity-profile file, and a check against an expected state.

Found by diffing copies taken before and after a change on the device (Edge 1040, firmware 31.33).
Garmin doesn't document any of this, so a firmware update can move or rename a field; that is what
`check` is for.

- ClimbPro: message 13, field 63 (1 on, 0 off). A written value showed in the menu after one restart.
- Road hazard warnings, master switch: message 12, field 23 (1 on, 0 off). Turning it off on the
  device also cleared the low 5 bits of message 12, field 25 (0xFFFFFFFF -> 0xFFFFFFE0), most likely
  the five hazard types; writes copy that. A written value showed in the menu only after a second restart.
- Recurring time alert: message 16, the slot whose field 1 is 0 (time); field 2 = interval in ms,
  field 3 = enabled (1) or off (0).
"""
from __future__ import annotations

import re

from . import fit

HAZARD_TYPES_ON, HAZARD_TYPES_OFF = 0xFFFFFFFF, 0xFFFFFFE0
NAMES = ("climbpro", "hazards", "time_alert_min")
# Firmware versions on which the field locations above were checked by a one-setting diff and a write-back.
VERIFIED = {"Edge 1040": ("31.33",)}


def device_info(xml_text: str) -> tuple[str, str]:
    """(model, firmware) from a GarminDevice.xml, e.g. ('Edge 1040 Solar', '31.33')."""
    model = re.search(r"<Model>.*?<Description>(.*?)</Description>", xml_text, re.S)
    ver = re.search(r"<Model>.*?<SoftwareVersion>(\d+)</SoftwareVersion>", xml_text, re.S)
    if not model or not ver:
        raise fit.FitError("GarminDevice.xml has no Model description or SoftwareVersion")
    v = int(ver.group(1))
    return model.group(1).strip(), f"{v // 100}.{v % 100:02d}"


def firmware_note(model: str, firmware: str) -> tuple[bool, str]:
    """(verified?, one line) for a device's model and firmware."""
    for family, versions in VERIFIED.items():
        if model.startswith(family):
            if firmware in versions:
                return True, f"{model}, firmware {firmware}: field locations verified on this version"
            return False, (f"{model}, firmware {firmware}: field locations verified only on {', '.join(versions)}; "
                           "re-verify with a one-setting diff before writing any fix")
    return False, f"{model}, firmware {firmware}: no field locations verified for this model"


def _one(f: fit.FitFile, gnum: int) -> fit.Message:
    msgs = f.of(gnum)
    if not msgs:
        raise fit.FitError(f"no message {gnum} in this file")
    return msgs[0]


def _time_slot(f: fit.FitFile):
    return next((m for m in f.of(16) if m.get(1) == 0), None)


def read(f: fit.FitFile) -> dict:
    """{'climbpro': 'on'|'off', 'hazards': 'on'|'off', 'time_alert_min': minutes or 'off'}"""
    onoff = lambda v: "on" if v == 1 else "off"
    slot = _time_slot(f)
    alert = "off"
    if slot is not None and slot.get(3) == 1 and isinstance(slot.get(2), int):
        alert = round(slot.get(2) / 60000, 3)
        alert = int(alert) if alert == int(alert) else alert
    return {"climbpro": onoff(_one(f, 13).get(63)), "hazards": onoff(_one(f, 12).get(23)), "time_alert_min": alert}


def edits(f: fit.FitFile, want: dict) -> list:
    """The (field, value) edits that bring the file to `want` (any subset of NAMES)."""
    out = []
    unknown = set(want) - set(NAMES)
    if unknown:
        raise fit.FitError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    if "climbpro" in want:
        out.append((_one(f, 13).fields[63], 1 if want["climbpro"] == "on" else 0))
    if "hazards" in want:
        m = _one(f, 12)
        on = want["hazards"] == "on"
        out.append((m.fields[23], 1 if on else 0))
        if 25 in m.fields:
            out.append((m.fields[25], HAZARD_TYPES_ON if on else HAZARD_TYPES_OFF))
    if "time_alert_min" in want:
        slot = _time_slot(f)
        if slot is None:
            raise fit.FitError("no time-alert slot (message 16, type 0) in this file")
        if want["time_alert_min"] == "off":
            out.append((slot.fields[3], 0))
        else:
            out += [(slot.fields[2], int(float(want["time_alert_min"]) * 60000)), (slot.fields[3], 1)]
    return out


def mismatches(f: fit.FitFile, want: dict) -> list[tuple[str, object, object]]:
    """[(setting, expected, actual)] for every setting in `want` that the file doesn't match."""
    have = read(f)
    return [(k, v, have[k]) for k, v in want.items() if have.get(k) != v]
