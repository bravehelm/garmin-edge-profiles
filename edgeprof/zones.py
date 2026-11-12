"""Heart-rate zones in an Edge's settings file (`Garmin/Settings/Settings.fit`), read-only.

The settings file holds one zones-target record (message 7) per sport and the heart-rate zone
tables (message 8). The fields named here are the documented ones from Garmin's FIT profile:

- message 7 (zones_target): 254 = sport (0 generic, 1 running, 2 cycling, ...), 1 = max heart rate,
  2 = threshold (LTHR), 3 = FTP (watts), 5 = how zones are calculated (hr_calc_type).
- message 8 (hr_zone): 1 = upper bound in bpm, 2 = name.

Observed on an Edge 1040 (firmware 31.33): message 8 comes in tables of six rows, table k for sport k.
Rows 0-4 are the floors of zones 1-5 and row 5 is the max. Message 7 also carries undocumented fields
(8 to 13). `zones` prints them raw. Use `diff` on copies taken before and after one change on the
device to learn which one is which (auto-detect, for example).
"""
from __future__ import annotations

from . import fit

ZONES_TARGET, HR_ZONE = 7, 8
SPORTS = {0: "generic", 1: "running", 2: "cycling", 3: "transition", 4: "fitness equipment"}
HR_CALC = {0: "custom", 1: "% max HR", 2: "% HRR", 3: "% LTHR"}
DOCUMENTED = {1, 2, 3, 5, 7, 254}
TABLE_ROWS = 6


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
            "floors": floors,
            "table_max": table[5] if floors else None,
            "other": {n: fl.value for n, fl in sorted(m.fields.items()) if n not in DOCUMENTED},
        })
    return out
