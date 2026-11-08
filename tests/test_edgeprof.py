"""Tests build their own synthetic FIT files; no real device files are used or committed."""
import struct
import tempfile
import unittest
from pathlib import Path

from edgeprof import cli, fit


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


if __name__ == "__main__":
    unittest.main()
