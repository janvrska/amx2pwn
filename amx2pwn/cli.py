"""Command line interface."""

import argparse
import os
import sys

from .amxfile import Amx, AmxError
from .decompiler import Decompiler
from .listing import Disassembler
from .literals import set_codepage
from .render import Renderer


def is_own_output(path):
    """True when the file does not exist or was written by amx2pwn."""
    try:
        with open(path, "rb") as f:
            head = f.read(200)
    except OSError:
        return True
    return b"Decompiled from:" in head


def process(path, outpath=None, asm=True, shift=None, enc="latin-1", mode="pwn", force=False):
    """Decompile one .amx file into a .pwn file (and an .asm listing)."""
    raw = open(path, "rb").read()
    amx = Amx(raw, shift)
    for w in amx.warnings:
        print("  warning: " + w)
    base = os.path.splitext(outpath or path)[0]
    pwn = outpath or base + ".pwn"
    if not force and not is_own_output(pwn):
        raise AmxError("%s already exists and was not written by amx2pwn "
                       "(use -o to pick another name, or --force)" % pwn)
    dis = Disassembler(amx)
    if mode == "emit":
        with open(pwn, "w", encoding=enc, errors="replace", newline="\n") as f:
            dis.write_pwn(f, os.path.basename(path))
    else:
        d = Decompiler(amx).run()
        with open(pwn, "w", encoding=enc, errors="replace", newline="\n") as f:
            Renderer(d).render(f, os.path.basename(path))
        bad = [fi.name for fi in d.funcs if getattr(fi, "failed", False)]
        if bad:
            print("  warning: %d functions could not be decompiled: %s" % (len(bad), ", ".join(bad[:10])))
    if asm:
        with open(base + ".asm", "w", encoding=enc, errors="replace", newline="\n") as f:
            dis.write_asm(f)
    print("%s -> %s  (%d functions, %d natives, %d publics, %d strings%s)" % (
        path, pwn, len(dis.funcs), len(amx.native_list), len(amx.public_list),
        len(dis.strings), ", shift=%d" % amx.shift if amx.shift else ""))


def main():
    ap = argparse.ArgumentParser(prog="amx2pwn", description="AMX -> PWN decompiler")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--output", help="output .pwn (single input file only)")
    ap.add_argument("--no-asm", action="store_true", help="do not write the .asm listing")
    ap.add_argument("--emit", action="store_true",
                    help="print function bodies as #emit instead of decompiling them")
    ap.add_argument("--shift", type=int, default=None,
                    help="string character decoding: char = cell >> N (default: auto)")
    ap.add_argument("--utf8", action="store_true",
                    help="convert characters from cp1250 to UTF-8 (default: bytes 1:1 as in the .amx)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing .pwn even if amx2pwn did not write it")
    args = ap.parse_args()
    if args.utf8:
        set_codepage("cp1250")
    rc = 0
    for f in args.files:
        try:
            process(f, args.output if len(args.files) == 1 else None, not args.no_asm, args.shift,
                    "utf-8" if args.utf8 else "latin-1", "emit" if args.emit else "pwn", args.force)
        except (AmxError, OSError) as e:
            print("%s: ERROR: %s" % (f, e), file=sys.stderr)
            rc = 1
    sys.exit(rc)
