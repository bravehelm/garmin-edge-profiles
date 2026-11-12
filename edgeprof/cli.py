"""edgeprof: read, diff and edit Garmin Edge activity-profile files over USB.

    python -m edgeprof show  Cycling.fit            # data screens and recurring alerts
    python -m edgeprof dump  Cycling.fit            # every message and field, raw
    python -m edgeprof diff  before.fit after.fit   # what changed between two copies
    python -m edgeprof set-screen Cycling.fit --screen 1 --fields "Speed,Cadence,Timer" --out new.fit
    python -m edgeprof get   Cycling.fit            # ClimbPro, road hazard warnings, time alert
    python -m edgeprof set   Cycling.fit --climbpro off --hazards off --time-alert 15 --out new.fit
    python -m edgeprof check expected.json Sports/ [--fix staging/]
    python -m edgeprof zones Settings.fit           # heart-rate zones per sport (read-only)

Writing never touches the source file: `set-screen` writes a copy. Put that copy in the Edge's
`Garmin/NewFiles/` folder and the device imports it at the next start-up.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import fit, names, settings, zones

SCREEN, ALERT = 14, 16


def _load(path: str) -> fit.FitFile:
    data = Path(path).read_bytes()
    f = fit.parse(data)
    if not fit.check_crc(data):
        print(f"warning: {path}: file CRC does not match", file=sys.stderr)
    return f


def _fields(ids) -> str:
    ids = ids if isinstance(ids, list) else [ids]
    return ", ".join(names.field_name(i) for i in ids if i != 65535) or "(none)"


def show(args) -> int:
    f = _load(args.file)
    print("Data screens (message 14):")
    print(f"  {'slot':>4}  {'on':>2}  {'order':>5}  {'hidden':>6}  {'type':<10}  fields")
    for m in f.of(SCREEN):
        ids = m.get(7, [])
        count = m.get(3)
        shown = ids[:count] if isinstance(ids, list) and isinstance(count, int) and count < 255 else ids
        on = "y" if m.get(1) == 1 else "-"
        stype = names.SCREEN_TYPES.get(m.get(10), str(m.get(10, "")))
        print(f"  {m.get(254, '?'):>4}  {on:>2}  {str(m.get(9, '')):>5}  {str(m.get(12, '')):>6}  {stype:<10}  {_fields(shown)}")
    alerts = f.of(ALERT)
    if alerts:
        print("Recurring alerts (message 16):")
        for m in alerts:
            kind = {0: "time"}.get(m.get(1), f"type {m.get(1)}")
            val = m.get(2)
            if kind == "time" and isinstance(val, int):
                val = f"{val / 60000:g} min"
            print(f"  {kind:<8} every {val}  {'on' if m.get(3) == 1 else 'off'}")
    return 0


def dump(args) -> int:
    f = _load(args.file)
    for m in f.messages:
        label = names.MESSAGES.get(m.global_num, "")
        vals = "  ".join(f"{n}={fl.value}" for n, fl in sorted(m.fields.items()))
        print(f"#{m.index:<4} msg {m.global_num:<5} {label:<16} {vals}")
    return 0


def _keyed(f: fit.FitFile):
    """Key messages by (message number, occurrence) so two copies of a profile line up."""
    seen: dict[int, int] = {}
    out = {}
    for m in f.messages:
        k = seen.get(m.global_num, 0)
        seen[m.global_num] = k + 1
        out[(m.global_num, k)] = m
    return out


def diff(args) -> int:
    a, b = _keyed(_load(args.before)), _keyed(_load(args.after))
    changes = 0
    for key in sorted(set(a) | set(b)):
        ma, mb = a.get(key), b.get(key)
        label = f"msg {key[0]} #{key[1]}"
        if ma is None or mb is None:
            print(f"{label}: only in {'after' if ma is None else 'before'}")
            changes += 1
            continue
        for n in sorted(set(ma.fields) | set(mb.fields)):
            va, vb = ma.get(n), mb.get(n)
            if va != vb:
                print(f"{label} field {n}: {va} -> {vb}")
                changes += 1
    print(f"{changes} difference(s)" if changes else "no differences")
    return 0


def set_screen(args) -> int:
    f = _load(args.file)
    target = [m for m in f.of(SCREEN) if m.get(254) == args.screen]
    if not target:
        print(f"no data screen with slot {args.screen}", file=sys.stderr)
        return 2
    m = target[0]
    ids = [names.field_id(t) for t in args.fields.split(",") if t.strip()]
    slots = m.fields[7].size // 2
    if len(ids) > slots:
        print(f"a screen holds at most {slots} fields", file=sys.stderr)
        return 2
    edits = [(m.fields[7], ids + [65535] * (slots - len(ids)))]
    if 3 in m.fields:
        edits.append((m.fields[3], len(ids)))
    out = Path(args.out)
    if out.resolve() == Path(args.file).resolve():
        print("--out must be a new file; the source is never overwritten", file=sys.stderr)
        return 2
    out.write_bytes(fit.patch(f, edits))
    print(f"wrote {out}: screen {args.screen} = {_fields(ids)}")
    return 0


def get(args) -> int:
    for k, v in settings.read(_load(args.file)).items():
        print(f"{k}: {v}")
    return 0


def _want(args) -> dict:
    want = {}
    if args.climbpro:
        want["climbpro"] = args.climbpro
    if args.hazards:
        want["hazards"] = args.hazards
    if args.time_alert:
        want["time_alert_min"] = "off" if args.time_alert == "off" else float(args.time_alert)
    return want


def set_(args) -> int:
    want = _want(args)
    if not want:
        print("nothing to set: give --climbpro, --hazards or --time-alert", file=sys.stderr)
        return 2
    out = Path(args.out)
    if out.resolve() == Path(args.file).resolve():
        print("--out must be a new file; the source is never overwritten", file=sys.stderr)
        return 2
    f = _load(args.file)
    out.write_bytes(fit.patch(f, settings.edits(f, want)))
    print(f"wrote {out}: " + ", ".join(f"{k} {v}" for k, v in settings.read(_load(str(out))).items()))
    return 0


def check(args) -> int:
    """Compare every profile named in the expected-state JSON with its copy in `sports`.
    Exit 0 when all match, 1 when any differ. --fix DIR writes corrected copies there (for NewFiles)."""
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8"))
    xml = Path(args.device_xml) if args.device_xml else Path(args.sports).parent / "GarminDevice.xml"
    trusted = True
    if xml.exists():
        model, firmware = settings.device_info(xml.read_text(encoding="utf-8", errors="replace"))
        trusted, note = settings.firmware_note(model, firmware)
        print(note)
    else:
        print(f"firmware unknown: no {xml} (copy GarminDevice.xml next to the Sports folder, or pass --device-xml)")
    if args.fix and not trusted and not args.trust_firmware:
        print("not writing fixes on an unverified firmware (--trust-firmware to override)", file=sys.stderr)
        args.fix = None
    bad = 0
    for name, want in expected.items():
        if name.startswith("_"):
            continue
        path = Path(args.sports) / name
        if not path.exists():
            print(f"{name}: MISSING")
            bad += 1
            continue
        f = _load(str(path))
        diffs = settings.mismatches(f, want)
        if not diffs:
            print(f"{name}: ok")
            continue
        bad += 1
        print(f"{name}: " + "; ".join(f"{k} is {have}, want {v}" for k, v, have in diffs))
        if args.fix:
            out = Path(args.fix) / name
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(fit.patch(f, settings.edits(f, {k: v for k, v, _ in diffs})))
            print(f"  fixed copy: {out}")
    return 1 if bad else 0


def zones_(args) -> int:
    rows = zones.read(_load(args.file))
    if not rows:
        print("no heart-rate zone records (message 7); use the Edge's Garmin/Settings/Settings.fit")
        return 1
    for r in rows:
        floors = "/".join(map(str, r["floors"])) if r["floors"] else "(no table)"
        line = f"{r['sport']:<17} max {r['max'] or '-':>3}  LTHR {r['lthr'] or '-':>3}  {r['method']:<8}  floors {floors}"
        if r["table_max"] is not None and r["table_max"] != r["max"]:
            line += f" (table max {r['table_max']})"
        print(line)
        print(f"{'':17} undocumented: " + "  ".join(f"{k}={v}" for k, v in r["other"].items()))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="edgeprof", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show"); s.add_argument("file"); s.set_defaults(fn=show)
    s = sub.add_parser("dump"); s.add_argument("file"); s.set_defaults(fn=dump)
    s = sub.add_parser("diff"); s.add_argument("before"); s.add_argument("after"); s.set_defaults(fn=diff)
    s = sub.add_parser("set-screen")
    s.add_argument("file"); s.add_argument("--screen", type=int, required=True)
    s.add_argument("--fields", required=True, help="comma-separated names or numeric IDs")
    s.add_argument("--out", required=True); s.set_defaults(fn=set_screen)
    s = sub.add_parser("get", help="named settings: ClimbPro, road hazard warnings, time alert")
    s.add_argument("file"); s.set_defaults(fn=get)
    s = sub.add_parser("set", help="write a copy with named settings changed")
    s.add_argument("file"); s.add_argument("--climbpro", choices=("on", "off"))
    s.add_argument("--hazards", choices=("on", "off")); s.add_argument("--time-alert", help="minutes, or off")
    s.add_argument("--out", required=True); s.set_defaults(fn=set_)
    s = sub.add_parser("check", help="compare a copied Sports folder with an expected-state JSON")
    s.add_argument("expected"); s.add_argument("sports"); s.add_argument("--fix", help="write corrected copies here")
    s.add_argument("--device-xml", help="GarminDevice.xml (default: next to the Sports folder)")
    s.add_argument("--trust-firmware", action="store_true", help="write fixes even on a firmware not yet verified")
    s.set_defaults(fn=check)
    s = sub.add_parser("zones", help="heart-rate zones per sport from Garmin/Settings/Settings.fit (read-only)")
    s.add_argument("file"); s.set_defaults(fn=zones_)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (fit.FitError, KeyError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
