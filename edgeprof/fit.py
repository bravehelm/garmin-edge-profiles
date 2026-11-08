"""Minimal FIT reader/patcher (stdlib only).

Reads every record of a FIT file and remembers where each field's bytes live, so a field can be
rewritten in place (same size) and the file CRC recomputed. It does not re-encode files; that keeps
edits byte-exact and leaves everything the tool doesn't understand untouched.

FIT format reference: Garmin's FIT protocol documentation (https://developer.garmin.com/fit/protocol/).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

_CRC_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
              0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)

# base type number (low 5 bits) -> (struct code, size, invalid value)
_BASE = {
    0: ("B", 1, 0xFF), 1: ("b", 1, 0x7F), 2: ("B", 1, 0xFF), 3: ("h", 2, 0x7FFF), 4: ("H", 2, 0xFFFF),
    5: ("i", 4, 0x7FFFFFFF), 6: ("I", 4, 0xFFFFFFFF), 7: ("s", 1, None), 8: ("f", 4, None), 9: ("d", 8, None),
    10: ("B", 1, 0x00), 11: ("H", 2, 0x0000), 12: ("I", 4, 0x00000000), 13: ("B", 1, 0xFF),
    14: ("q", 8, 0x7FFFFFFFFFFFFFFF), 15: ("Q", 8, 0xFFFFFFFFFFFFFFFF), 16: ("Q", 8, 0),
}


def crc16(data: bytes, crc: int = 0) -> int:
    for byte in data:
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[byte & 0xF]
        tmp = _CRC_TABLE[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ _CRC_TABLE[(byte >> 4) & 0xF]
    return crc


class FitError(ValueError):
    pass


@dataclass
class Field:
    num: int
    offset: int      # absolute byte offset in the file
    size: int
    base: int        # base type byte
    big_endian: bool
    raw: bytes

    @property
    def value(self):
        code, width, _ = _BASE.get(self.base & 0x1F, ("B", 1, None))
        if code == "s":
            return self.raw.split(b"\0", 1)[0].decode("utf-8", "replace")
        if self.size % width:
            return self.raw.hex()
        n = self.size // width
        vals = struct.unpack((">" if self.big_endian else "<") + code * n, self.raw)
        return vals[0] if n == 1 else list(vals)

    def encode(self, value) -> bytes:
        code, width, _ = _BASE.get(self.base & 0x1F, ("B", 1, None))
        if code == "s":
            raw = str(value).encode()[: self.size - 1]
            return raw + b"\0" * (self.size - len(raw))
        vals = value if isinstance(value, (list, tuple)) else [value]
        if len(vals) * width != self.size:
            raise FitError(f"field {self.num}: need {self.size // width} values, got {len(vals)}")
        return struct.pack((">" if self.big_endian else "<") + code * len(vals), *vals)


@dataclass
class Message:
    index: int          # position among data messages in the file
    global_num: int
    offset: int
    fields: dict[int, Field] = field(default_factory=dict)

    def get(self, num, default=None):
        f = self.fields.get(num)
        return default if f is None else f.value


@dataclass
class FitFile:
    data: bytes
    header_size: int
    messages: list[Message]

    def of(self, global_num: int) -> list[Message]:
        return [m for m in self.messages if m.global_num == global_num]


def parse(data: bytes) -> FitFile:
    if len(data) < 12 or data[8:12] != b".FIT":
        raise FitError("not a FIT file")
    hsize = data[0]
    data_size = struct.unpack_from("<I", data, 4)[0]
    end = hsize + data_size
    if end + 2 > len(data):
        raise FitError("file is truncated")
    defs: dict[int, tuple] = {}
    msgs: list[Message] = []
    pos = hsize
    while pos < end:
        h = data[pos]
        start = pos
        pos += 1
        if h & 0x80:                       # compressed-timestamp data message
            local = (h >> 5) & 0x3
        elif h & 0x40:                     # definition message
            local = h & 0x0F
            arch = data[pos + 1]
            big = arch == 1
            gnum = struct.unpack_from(">H" if big else "<H", data, pos + 2)[0]
            nf = data[pos + 4]
            pos += 5
            fields = []
            for _ in range(nf):
                fields.append((data[pos], data[pos + 1], data[pos + 2]))
                pos += 3
            dev_size = 0
            if h & 0x20:
                nd = data[pos]
                pos += 1
                for _ in range(nd):
                    dev_size += data[pos + 1]
                    pos += 3
            defs[local] = (gnum, big, fields, dev_size)
            continue
        else:
            local = h & 0x0F
        if local not in defs:
            raise FitError(f"data message at byte {start} uses undefined local type {local}")
        gnum, big, fields, dev_size = defs[local]
        m = Message(index=len(msgs), global_num=gnum, offset=start)
        for num, size, base in fields:
            m.fields[num] = Field(num, pos, size, base, big, data[pos:pos + size])
            pos += size
        pos += dev_size
        msgs.append(m)
    return FitFile(data=data, header_size=hsize, messages=msgs)


def check_crc(data: bytes) -> bool:
    hsize = data[0]
    end = hsize + struct.unpack_from("<I", data, 4)[0]
    return crc16(data[:end]) == struct.unpack_from("<H", data, end)[0]


def patch(fit: FitFile, edits: list[tuple[Field, object]]) -> bytes:
    """Return a copy of the file with each field rewritten in place and the file CRC recomputed."""
    out = bytearray(fit.data)
    for f, value in edits:
        raw = f.encode(value)
        out[f.offset:f.offset + f.size] = raw
    end = fit.header_size + struct.unpack_from("<I", out, 4)[0]
    struct.pack_into("<H", out, end, crc16(bytes(out[:end])))
    return bytes(out)
