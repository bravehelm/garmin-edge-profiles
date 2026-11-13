"""Heart-rate zones in an Edge's settings file (`Garmin/Settings/Settings.fit`), read-only.

The settings file holds one zones-target record (message 7) per sport and the heart-rate zone
tables (message 8). The fields named here are the documented ones from Garmin's FIT profile:

- message 7 (zones_target): 254 = sport (0 generic, 1 running, 2 cycling, ...), 1 = max heart rate,
  2 = threshold (LTHR), 3 = FTP (watts), 5 = how zones are calculated (hr_calc_type).
- message 8 (hr_zone): 1 = upper bound in bpm, 2 = name.

Auto-detect switches, found 2026-11-13 by turning both off on an Edge 1040 (firmware 31.33) and diffing
copies of Settings.fit taken before and after:

- lactate threshold auto-detect: message 2 (device_settings), field 80, 1 on / 0 off. Garmin's FIT profile
  names this field lactate_threshold_autodetect_enabled.
- max HR auto-detect: message 7, field 10 of that sport's record, 1 on / 0 off (undocumented; turning it off
  in the Edge's menu changed only the cycling record).

Observed on the same Edge: message 8 comes in tables of six rows, table k for sport k. Rows 0-4 are the
floors of zones 1-5 and row 5 is the max. Message 7 fields 8, 9 and 11-13 are still unknown; `zones`
prints them raw.
"""
from __future__ import annotations

from . import fit

DEVICE_SETTINGS, ZONES_TARGET, HR_ZONE = 2, 7, 8
LT_AUTO, MAX_AUTO = 80, 10
SPORTS = {0: "generic", 1: "running", 2: "cycling", 3: "transition", 4: "fitness equipment"}
HR_CALC = {0: "custom", 1: "% max HR", 2: "% HRR", 3: "% LTHR"}
DOCUMENTED = {1, 2, 3, 5, 7, MAX_AUTO, 254}
TABLE_ROWS = 6


def _onoff(v):
    return {1: "on", 0: "off"}.get(v, "-" if v is None else str(v))


def _bpm(v):
    return None if v in (None, 0, 255) else v


def read(f: fit.FitFile) -> list[dict]:
    """One dict per zones-target record: sport, max, lthr, ftp, method, floors (Z1-Z5 or None), other."""
    rows = {m.get(254): m.get(1) for m in f.of(HR_ZONE)}
    out = []
    for m in f.of(ZONES_TARGET):
        sport = m.get(254)
        table = [rows.get(sport * TABLE_ROWS + i) for i in range(TABLE_ROWS)] if isinstance(sport, int) else []
        floors = table[:5] if len(table) == TABLE_ROWS and None not in table else None
        out.append({
            "sport": SPORTS.get(sport, f"sport {sport}"),
            "max": _bpm(m.get(1)),
            "lthr": _bpm(m.get(2)),
            "ftp": m.get(3) if m.get(3) not in (None, 0xFFFF) else None,
            "method": HR_CALC.get(m.get(5), m.get(5)),
            "max_autodetect": _onoff(m.get(MAX_AUTO)),
            "floors": floors,
            "table_max": table[5] if floors else None,
            "other": {n: fl.value for n, fl in sorted(m.fields.items()) if n not in DOCUMENTED},
        })
    return out


def lt_autodetect(f: fit.FitFile) -> str:
    """'on' / 'off' for the device-wide lactate threshold auto-detect, '-' if the file has no such field."""
    m = f.of(DEVICE_SETTINGS)
    return _onoff(m[0].get(LT_AUTO)) if m else "-"


def edits(f: fit.FitFile, lt: str | None = None, max_hr: str | None = None, sport: str = "cycling") -> list:
    """(field, value) edits that set the auto-detect switches. lt / max_hr are 'on', 'off' or None (leave)."""
    out = []
    if lt is not None:
        m = f.of(DEVICE_SETTINGS)
        if not m or LT_AUTO not in m[0].fields:
            raise fit.FitError("no lactate threshold auto-detect field (message 2, field 80); is this Settings.fit?")
        out.append((m[0].fields[LT_AUTO], 1 if lt == "on" else 0))
    if max_hr is not None:
        num = next((k for k, v in SPORTS.items() if v == sport), None)
        rec = [m for m in f.of(ZONES_TARGET) if m.get(254) == num]
        if not rec or MAX_AUTO not in rec[0].fields:
            raise fit.FitError(f"no max HR auto-detect field for {sport} (message 7, field 10)")
        out.append((rec[0].fields[MAX_AUTO], 1 if max_hr == "on" else 0))
    return out
