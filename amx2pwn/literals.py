"""Formatting of Pawn literals: strings, floats, characters and integers."""

import struct

from .amxfile import PACKED


# Code page of the strings in the .amx (None = keep the bytes 1:1).
_codepage = None


def set_codepage(name):
    """Decode string bytes from this code page before writing them out (e.g. "cp1250")."""
    global _codepage
    _codepage = name


def pawn_str(s):
    """Python string -> Pawn string literal (a PACKED prefix gives !"...")."""
    if _codepage:
        s = s.encode("latin-1").decode(_codepage, "replace")
    packed = s.startswith(PACKED)
    if packed:
        s = s[1:]
    out = []
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32 or o == 127:
            out.append("\\%d;" % o)
        else:
            out.append(ch)
    return ("!" if packed else "") + '"' + "".join(out) + '"'


def as_float(v):
    f = struct.unpack("<f", struct.pack("<I", v & 0xFFFFFFFF))[0]
    return f


def float_str(v):
    s = ("%.4f" % as_float(v)).rstrip("0")
    return s + "0" if s.endswith(".") else s


def looks_float(v):
    if not (0x3A000000 <= (v & 0x7FFFFFFF) <= 0x4B000000):
        return False
    f = as_float(v)
    s = ("%.4f" % f).rstrip("0")
    return abs(float(s) - f) < 1e-6 * max(1, abs(f))


def fmt_float_bits(v):
    """Shortest decimal form that compiles to exactly the same bits. None = not a float."""
    bits = v & 0xFFFFFFFF
    if bits == 0:
        return "0.0"
    raw = struct.pack("<I", bits)
    f = struct.unpack("<f", raw)[0]
    if f != f or abs(f) == float("inf") or abs(f) < 1e-6 or abs(f) > 1e9:
        return None
    for p in range(1, 12):
        s = "%.*f" % (p, f)
        if struct.pack("<f", float(s)) == raw:
            return s
    return None


def char_lit(v):
    if v == 0:
        return "EOS"
    esc = {10: "'\\n'", 13: "'\\r'", 9: "'\\t'", 39: "'\\''", 92: "'\\\\'"}
    if v in esc:
        return esc[v]
    if 32 <= v < 127:
        return "'%s'" % chr(v)
    return None


def nice_int(v):
    if v == 0x7FFFFFFF:
        return "cellmax"
    if v == -0x80000000:
        return "cellmin"
    if abs(v) > 0xFFFF:
        t = str(abs(v))
        if t.endswith("000") or set(t) == {"9"}:
            return str(v)
        return "0x%08X" % (v & 0xFFFFFFFF)
    return None
