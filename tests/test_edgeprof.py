"""Tests build their own synthetic FIT files; no real device files are used or committed."""
import json
import struct
import tempfile
import unittest
from pathlib import Path

from edgeprof import cli, fit, settings


def _definition(local, gnum, fields):
    out = bytes([0x40 | local, 0, 0]) + struct.pack("<H", gnum) + bytes([len(fields)])
    for num, size, base in fields:
        out += bytes([num, size, base])
    return out


def make_profile(screens, alert_ms=900000):
    body = _definition(0, 0, [(0, 1, 0x00), (3, 4, 0x8C)]) + bytes([0, 4]) + struct.pack("<I", 0)  # file_id, serial 0
    body += _definition(1, 14, [(254, 2, 0x84), (1, 1, 0x00), (3, 1, 0x02), (7, 20, 0x84), (9, 1, 0x02), (10, 1, 0x00)])
    for slot, ids, stype in screens:
        padded = ids + [65535] * (10 - len(ids))
        body += bytes([1]) + struct.pack("<HBB10HBB", slot, 1, len(ids), *padded, slot, stype)
    body += _definition(2, 16, [(1, 1, 0x00), (2, 4, 0x86), (3, 1, 0x00)])
    body += bytes([2]) + struct.pack("<BIB", 0, alert_ms, 1)
    header = bytes([14, 0x20]) + struct.pack("<HI", 2100, len(body)) + b".FIT"
    header += struct.pack("<H", fit.crc16(header))
    data = header + body
    return data + struct.pack("<H", fit.crc16(data))


class EdgeProfTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "Cycling.fit"
        self.src.write_bytes(make_profile([(0, [48, 6, 56], 0), (1, [522, 511], 38)]))

    def test_parse_reads_screens_and_alert(self):
        f = fit.parse(self.src.read_bytes())
        screens = f.of(14)
        self.assertEqual([m.get(254) for m in screens], [0, 1])
        self.assertEqual(screens[0].get(7)[:3], [48, 6, 56])
        self.assertEqual(f.of(16)[0].get(2), 900000)
        self.assertTrue(fit.check_crc(self.src.read_bytes()))

    def test_set_screen_writes_a_valid_copy(self):
        out = self.tmp / "new.fit"
        rc = cli.main(["set-screen", str(self.src), "--screen", "1", "--fields", "Duration,Cadence,511", "--out", str(out)])
        self.assertEqual(rc, 0)
        data = out.read_bytes()
        self.assertTrue(fit.check_crc(data))
        m = [m for m in fit.parse(data).of(14) if m.get(254) == 1][0]
        self.assertEqual(m.get(7)[:4], [522, 3, 511, 65535])
        self.assertEqual(m.get(3), 3)
        self.assertEqual(len(data), len(self.src.read_bytes()))

    def test_set_screen_refuses_to_overwrite_source(self):
        before = self.src.read_bytes()
        rc = cli.main(["set-screen", str(self.src), "--screen", "0", "--fields", "Speed", "--out", str(self.src)])
        self.assertEqual(rc, 2)
        self.assertEqual(self.src.read_bytes(), before)

    def test_diff_finds_the_changed_field(self):
        other = self.tmp / "after.fit"
        other.write_bytes(make_profile([(0, [48, 6, 56], 0), (1, [522, 511], 38)], alert_ms=600000))
        a, b = cli._keyed(fit.parse(self.src.read_bytes())), cli._keyed(fit.parse(other.read_bytes()))
        self.assertEqual(a[(16, 0)].get(2), 900000)
        self.assertEqual(b[(16, 0)].get(2), 600000)
        self.assertEqual(cli.main(["diff", str(self.src), str(other)]), 0)

    def test_rejects_non_fit(self):
        bad = self.tmp / "bad.fit"
        bad.write_bytes(b"not a fit file at all")
        with self.assertRaises(fit.FitError):
            fit.parse(bad.read_bytes())


def make_settings_profile(climbpro=1, hazards=1, alert_ms=900000, alert_on=1):
    """A profile with the messages `settings` reads: 12 (f23, f25), 13 (f63) and a type-0 slot in 16."""
    body = _definition(0, 0, [(0, 1, 0x00), (3, 4, 0x8C)]) + bytes([0, 4]) + struct.pack("<I", 0)
    body += _definition(1, 12, [(23, 1, 0x00), (25, 4, 0x86)])
    body += bytes([1]) + struct.pack("<BI", hazards, 0xFFFFFFFF if hazards else 0xFFFFFFE0)
    body += _definition(2, 13, [(7, 1, 0x00), (63, 1, 0x00)])
    body += bytes([2]) + struct.pack("<BB", 1, climbpro)
    body += _definition(3, 16, [(1, 1, 0x00), (2, 4, 0x86), (3, 1, 0x00)])
    body += bytes([3]) + struct.pack("<BIB", 1, 1609344, 0) + bytes([3]) + struct.pack("<BIB", 0, alert_ms, alert_on)
    header = bytes([14, 0x20]) + struct.pack("<HI", 2100, len(body)) + b".FIT"
    header += struct.pack("<H", fit.crc16(header))
    data = header + body
    return data + struct.pack("<H", fit.crc16(data))


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.sports = self.tmp / "Sports"
        self.sports.mkdir()
        (self.sports / "CyclingGRAVEL.fit").write_bytes(make_settings_profile())
        (self.sports / "CyclingROAD.fit").write_bytes(make_settings_profile(hazards=0, alert_on=0))

    def test_read(self):
        f = fit.parse((self.sports / "CyclingGRAVEL.fit").read_bytes())
        self.assertEqual(settings.read(f), {"climbpro": "on", "hazards": "on", "time_alert_min": 15})
        f = fit.parse((self.sports / "CyclingROAD.fit").read_bytes())
        self.assertEqual(settings.read(f), {"climbpro": "on", "hazards": "off", "time_alert_min": "off"})

    def test_set_changes_only_the_named_bytes(self):
        src, out = self.sports / "CyclingGRAVEL.fit", self.tmp / "new.fit"
        rc = cli.main(["set", str(src), "--climbpro", "off", "--hazards", "off", "--time-alert", "20", "--out", str(out)])
        self.assertEqual(rc, 0)
        data = out.read_bytes()
        self.assertTrue(fit.check_crc(data))
        self.assertEqual(len(data), len(src.read_bytes()))
        f = fit.parse(data)
        self.assertEqual(settings.read(f), {"climbpro": "off", "hazards": "off", "time_alert_min": 20})
        self.assertEqual(f.of(12)[0].get(25), settings.HAZARD_TYPES_OFF)   # as the device writes it
        self.assertEqual(f.of(16)[0].get(2), 1609344)                        # other alert slots untouched
        self.assertEqual(cli.main(["set", str(src), "--out", str(out)]), 2)  # nothing to set
        self.assertEqual(cli.main(["set", str(src), "--climbpro", "on", "--out", str(src)]), 2)

    def test_check_and_fix(self):
        expected = self.tmp / "expected.json"
        want = {"climbpro": "off", "hazards": "off", "time_alert_min": 15}
        expected.write_text(json.dumps({"_note": "ignored", "CyclingGRAVEL.fit": want,
                                        "CyclingROAD.fit": {"hazards": "off"}}))
        fixdir = self.tmp / "fix"
        self.assertEqual(cli.main(["check", str(expected), str(self.sports), "--fix", str(fixdir)]), 1)
        self.assertEqual([p.name for p in fixdir.iterdir()], ["CyclingGRAVEL.fit"])   # ROAD already matched
        fixed = fit.parse((fixdir / "CyclingGRAVEL.fit").read_bytes())
        self.assertEqual(settings.read(fixed), want)
        (self.sports / "CyclingGRAVEL.fit").write_bytes((fixdir / "CyclingGRAVEL.fit").read_bytes())
        self.assertEqual(cli.main(["check", str(expected), str(self.sports)]), 0)

    def test_check_reports_a_missing_profile(self):
        expected = self.tmp / "expected.json"
        expected.write_text(json.dumps({"CyclingMTB.fit": {"climbpro": "on"}}))
        self.assertEqual(cli.main(["check", str(expected), str(self.sports)]), 1)

    def test_unknown_setting_is_refused(self):
        f = fit.parse((self.sports / "CyclingGRAVEL.fit").read_bytes())
        with self.assertRaises(fit.FitError):
            settings.edits(f, {"autopause": "off"})

    def _xml(self, version):
        (self.tmp / "GarminDevice.xml").write_text(
            "<Device><Model><PartNumber>006-B0000-00</PartNumber><SoftwareVersion>%d</SoftwareVersion>"
            "<Description>Edge 1040 Solar</Description></Model></Device>" % version)

    def test_device_info_and_note(self):
        self._xml(3133)
        model, fw = settings.device_info((self.tmp / "GarminDevice.xml").read_text())
        self.assertEqual((model, fw), ("Edge 1040 Solar", "31.33"))
        self.assertTrue(settings.firmware_note(model, fw)[0])
        self.assertFalse(settings.firmware_note(model, "32.05")[0])
        self.assertFalse(settings.firmware_note("Edge 540", "20.10")[0])
        self.assertEqual(settings.device_info("<Model><SoftwareVersion>905</SoftwareVersion>"
                                              "<Description>Edge 1040</Description></Model>")[1], "9.05")

    def test_check_will_not_fix_on_unverified_firmware(self):
        expected = self.tmp / "expected.json"
        expected.write_text(json.dumps({"CyclingGRAVEL.fit": {"climbpro": "off"}}))
        fixdir = self.tmp / "fix"
        self._xml(3205)   # GarminDevice.xml next to the Sports folder, as copied off the device
        self.assertEqual(cli.main(["check", str(expected), str(self.sports), "--fix", str(fixdir)]), 1)
        self.assertFalse(fixdir.exists())
        self.assertEqual(cli.main(["check", str(expected), str(self.sports), "--fix", str(fixdir),
                                   "--trust-firmware"]), 1)
        self.assertTrue((fixdir / "CyclingGRAVEL.fit").exists())
        self._xml(3133)
        fixdir2 = self.tmp / "fix2"
        self.assertEqual(cli.main(["check", str(expected), str(self.sports), "--fix", str(fixdir2)]), 1)
        self.assertTrue((fixdir2 / "CyclingGRAVEL.fit").exists())


if __name__ == "__main__":
    unittest.main()
