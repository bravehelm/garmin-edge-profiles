# garmin-edge-profiles

Keep a Garmin Edge's activity-profile settings in files you can read, diff and edit, instead of
tapping through menus on the device.

An Edge stores each activity profile (data screens, alerts, and more) as a FIT file in
`Garmin/Sports/`. `edgeprof` reads those files, shows what's in them, compares two copies, and
writes an edited copy that the Edge imports from `Garmin/NewFiles/` at its next start-up. That
import path is the one the device itself declares for these files.

Status: early. Data screens (message 14) and recurring alerts (message 16) are decoded, plus two
on/off settings: ClimbPro and road hazard warnings (below). Everything else is shown raw by `dump`
and left byte-for-byte untouched by edits.

## Use

Python 3.9+, no dependencies.

```
python -m edgeprof show  Cycling.fit             # data screens and recurring alerts
python -m edgeprof dump  Cycling.fit             # every message and field, raw
python -m edgeprof diff  before.fit after.fit    # what changed between two copies
python -m edgeprof set-screen Cycling.fit --screen 1 --fields "Speed,Cadence,Timer" --out new.fit
python -m edgeprof get   Cycling.fit             # ClimbPro, road hazard warnings, time alert
python -m edgeprof set   Cycling.fit --climbpro off --hazards off --time-alert 15 --out new.fit
python -m edgeprof check expected.json Sports/ [--fix staging/]
```

**Keeping settings after a firmware update or reset:** list the settings you want per profile file
in a JSON file, copy `Garmin/Sports/` off the Edge, and run `check`. It prints `ok` or what differs
and exits 1 on any difference; `--fix DIR` writes corrected copies to put in `Garmin/NewFiles/`.

```json
{"CyclingGRAVEL.fit": {"climbpro": "off", "hazards": "off", "time_alert_min": 15},
 "CyclingRoadROAD.fit": {"climbpro": "on", "hazards": "off"}}
```

**Named settings** (Edge 1040, firmware 31.33; found by changing one setting on the device and
diffing; Garmin doesn't document them, so check again after an update):

| Setting | Where | Values |
|---|---|---|
| ClimbPro | message 13, field 63 | 1 on, 0 off |
| Road hazard warnings (master switch) | message 12, field 23 | 1 on, 0 off. Turning it off on the device also clears the low 5 bits of field 25 (0xFFFFFFFF to 0xFFFFFFE0), most likely the five hazard types; `set` does the same |
| Recurring time alert | message 16, slot with field 1 = 0 | field 2 = interval (ms), field 3 = 1 on, 0 off |

**Restart twice before trusting the menus.** After an import, a written ClimbPro value showed in
the menu after one restart; a written hazard value showed only after the second. The files were
right both times.
**Finding an undocumented setting:** copy the profile file off the Edge, change one setting on the
device, copy it again, and `diff` the two. The changed message and field is that setting.

**Safety:** nothing writes to the source file. `set-screen` writes a new file (same size, only the
edited bytes and the file checksum change). Back up `Garmin/Sports/` before copying anything to
the device.

On an Edge that connects over MTP (no drive letter on Windows), copy files with the file manager:
the device shows up under "This PC".

## How it works

A FIT file is a list of definition and data messages. `edgeprof/fit.py` records where every field's
bytes are, so an edit rewrites those bytes in place and recomputes the CRC, without re-encoding the
file. In a profile's data-screen records (message 14): field 254 is the screen slot, 1 on/off, 3 the
number of data fields shown, 7 the data-field IDs (ten 16-bit slots, 65535 = empty), 9 the order,
10 the screen type, 12 hidden.

## Device files and privacy

Real device files are never committed (see `.gitignore`): their `file_id` message carries the unit's
serial number. Tests build synthetic files.

## Credits

Data-field ID names were cross-checked against the table in
[Activity Profile Editor](https://github.com/fullcarbonbike/Activity-Profile-Editor) (MIT). FIT
structure follows Garmin's [FIT protocol documentation](https://developer.garmin.com/fit/protocol/).
Not affiliated with Garmin.

## License

MIT
