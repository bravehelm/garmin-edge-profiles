# garmin-edge-profiles

Keep a Garmin Edge's activity-profile settings in files you can read, diff and edit, instead of
tapping through menus on the device.

An Edge stores each activity profile (data screens, alerts, and more) as a FIT file in
`Garmin/Sports/`. `edgeprof` reads those files, shows what's in them, compares two copies, and
writes an edited copy that the Edge imports from `Garmin/NewFiles/` at its next start-up. That
import path is the one the device itself declares for these files.

Status: early. Data screens (message 14) and recurring alerts (message 16) are decoded, plus heart-rate
zones and their auto-detect switches (in `Settings.fit`, below), and two
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

`check` also reads the firmware version from `Garmin/GarminDevice.xml` (next to the copied `Sports`
folder, or `--device-xml`). The field locations are only known for the firmware versions listed in
`edgeprof/settings.py` (`VERIFIED`). On any other version it still reports, but it won't write fixes
until you re-verify with a one-setting diff (or pass `--trust-firmware`). A firmware update is exactly
when an undocumented field might move. If you verify a new version or model, a pull request adding it
to `VERIFIED` helps everyone.

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

**Heart-rate zones and auto-detect** live in `Garmin/Settings/Settings.fit`, not in the profile files. With auto-detect
on, the Edge raises max HR and LTHR on its own after rides, and Garmin Connect then syncs those raised values to your
other devices. `zones` shows the zones and both switches; `set-zones` writes a copy with the switches changed:

```
python -m edgeprof zones Settings.fit
cycling           max 172  LTHR 150  % LTHR    floors 102/128/140/149/156  max HR auto-detect off
                  undocumented: 8=65535  9=0  11=1  12=1  13=7
lactate threshold auto-detect (all sports): off
python -m edgeprof set-zones Settings.fit --lt-autodetect off --max-autodetect off --out new.fit
```

| Setting | Where | Values |
|---|---|---|
| Lactate threshold auto-detect | message 2, field 80 (named `lactate_threshold_autodetect_enabled` in Garmin's FIT profile) | 1 on, 0 off |
| Max HR auto-detect | message 7, field 10 of the sport's record (cycling by default; `--sport`) | 1 on, 0 off |
| Max HR, LTHR, FTP, zone method | message 7, fields 1, 2, 3, 5 (documented) | read only |
| Zone tables | message 8, six rows per sport: floors of zones 1-5, then max | read only |

Both switches were found on an Edge 1040 (firmware 31.33) by turning them off in the device's menu and diffing
`Settings.fit`. `set-zones` on the before-copy produced the same two changed bytes. The Edge declares that settings
files (FIT type 2) can be imported from `Garmin/NewFiles/`. Only edit a copy taken off the Edge just before: the file
also holds sensors, bikes and the user profile, and an old copy would roll those back.

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
