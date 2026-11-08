"""Parser for compiled Pawn AMX files: header, tables, code/data and debug info."""

import struct

from .opcodes import OPCODES


AMX_FLAG_DEBUG = 0x02

AMX_FLAG_COMPACT = 0x04


class AmxError(Exception):
    pass


# marks a packed string (!"...") in the string table
PACKED = "\x01"


class Amx:
    """A parsed .amx file (16/32/64-bit cells, compact encoding, debug info)."""

    def __init__(self, raw, shift=None):
        self.raw = raw
        self.forced_shift = shift
        self.warnings = []
        self._parse_header()
        try:
            self._load_image()
            self._parse_tables()
            self._parse_debug()
        except (struct.error, ValueError, IndexError, OverflowError) as e:
            msg = "the file is damaged (%s)" % e
            if self.warnings:
                msg = "%s; %s" % (self.warnings[0], msg)
            raise AmxError(msg)

    # ---------------- header ----------------
    def _parse_header(self):
        r = self.raw
        if len(r) < 8:
            raise AmxError("file is too short")
        self.size, self.magic = struct.unpack_from("<iH", r, 0)
        cellsizes = {0xF1E0: 4, 0xF1E1: 8, 0xF1E2: 2}
        if self.magic not in cellsizes:
            if all(32 <= b < 127 or b in (9, 10, 13) for b in r[:64]):
                raise AmxError("this is a text file, not a compiled .amx")
            raise AmxError("unknown magic 0x%04X (not an AMX file?)" % self.magic)
        self.cell = cellsizes[self.magic]
        self.cfmt = {2: "h", 4: "i", 8: "q"}[self.cell]
        self.ufmt = self.cfmt.upper()
        self.mask = (1 << (8 * self.cell)) - 1
        (self.file_version, self.amx_version, self.flags, self.defsize,
         self.cod, self.dat, self.hea, self.stp, self.cip,
         self.publics, self.natives, self.libraries, self.pubvars,
         self.tags, self.nametable) = struct.unpack_from("<BBHHiiiiiiiiiii", r, 6)
        if self.file_version < 7:
            self.nametable = None   # older format: names stored inline in the tables
        if self.size > len(r):
            # Truncated file or a patched header (an old anti-decompiler trick).
            # Carry on with what is there; _load_image checks that the code is complete.
            self.warnings.append("header says the size is %d, but the file has only %d bytes"
                                 % (self.size, len(r)))
            self.size = len(r)

    def sval(self, v):
        """unsigned -> signed cell"""
        v &= self.mask
        return v - (1 << (8 * self.cell)) if v >> (8 * self.cell - 1) else v

    # ---------------- code + data ----------------
    def _expand(self, buf):
        """Compact encoding: every cell is a 7-bit varint, big-endian,
        bit 0x80 = continues, bit 0x40 of the first byte = sign."""
        out = []
        i, n = 0, len(buf)
        bits = 8 * self.cell
        while i < n:
            first = buf[i]
            c = 0
            cnt = 0
            while True:
                b = buf[i]
                i += 1
                cnt += 1
                c = (c << 7) | (b & 0x7F)
                if not (b & 0x80) or i >= n:
                    break
            if first & 0x40:
                c -= 1 << (7 * cnt)
            out.append(c & self.mask)
        return struct.pack("<%d%s" % (len(out), self.ufmt), *out)

    def _load_image(self):
        if self.flags & AMX_FLAG_COMPACT:
            img = self._expand(self.raw[self.cod:self.size])
        else:
            img = self.raw[self.cod:self.size]
        need = self.hea - self.cod
        if len(img) < need:
            img += b"\0" * (need - len(img))
        self.code = img[:self.dat - self.cod]
        self.data = img[self.dat - self.cod:self.hea - self.cod]
        self.ncode = len(self.code) // self.cell
        self.ndata = len(self.data) // self.cell
        self.code_cells = struct.unpack("<%d%s" % (self.ncode, self.ufmt), self.code[:self.ncode * self.cell])
        self.data_cells = struct.unpack("<%d%s" % (self.ndata, self.ufmt), self.data[:self.ndata * self.cell])

    # ---------------- tables ----------------
    def _name_at(self, ofs):
        r = self.raw
        end = r.index(b"\0", ofs)
        return r[ofs:end].decode("latin-1")

    def _table(self, start, end):
        res = []
        if not self.defsize:
            return res
        for p in range(start, end, self.defsize):
            addr = struct.unpack_from("<" + self.ufmt, self.raw, p)[0]
            if self.nametable is not None:
                nofs = struct.unpack_from("<I", self.raw, p + self.cell)[0]
                name = self._name_at(nofs)
            else:
                name = self.raw[p + self.cell:p + self.defsize].split(b"\0")[0].decode("latin-1")
            res.append((addr, name))
        return res

    def _parse_tables(self):
        self.public_list = self._table(self.publics, self.natives)
        self.native_list = [n for _, n in self._table(self.natives, self.libraries)]
        self.library_list = [n for _, n in self._table(self.libraries, self.pubvars)]
        self.pubvar_list = self._table(self.pubvars, self.tags)
        tags_end = self.nametable if self.nametable is not None else self.cod
        self.tag_list = self._table(self.tags, tags_end)

    # ---------------- debug info (amxdbg) ----------------
    def _parse_debug(self):
        self.dbg_files, self.dbg_lines, self.dbg_symbols, self.dbg_tags = [], [], [], {}
        self.has_debug = False
        p = self.size
        r = self.raw
        if len(r) - p < 22:
            return
        dsize, dmagic = struct.unpack_from("<iH", r, p)
        if dmagic != 0xF1EF:
            return
        try:
            (_fv, _av, _fl, nfiles, nlines, nsyms, ntags, nautom, nstates) = \
                struct.unpack_from("<BBhhhhhhh", r, p + 6)
            q = p + 22
            C = self.cell
            uf = "<" + self.ufmt

            def cstr(q):
                e = r.index(b"\0", q)
                return r[q:e].decode("latin-1"), e + 1

            for _ in range(nfiles):
                a = struct.unpack_from(uf, r, q)[0]
                name, q = cstr(q + C)
                self.dbg_files.append((a, name))
            for _ in range(nlines & 0xFFFF):
                a = struct.unpack_from(uf, r, q)[0]
                ln = struct.unpack_from("<i", r, q + C)[0]
                q += C + 4
                self.dbg_lines.append((a, ln))
            for _ in range(nsyms & 0xFFFF):
                addr = struct.unpack_from(uf, r, q)[0]
                tag = struct.unpack_from("<h", r, q + C)[0]
                cs, ce = struct.unpack_from("<" + self.ufmt * 2, r, q + C + 2)
                ident, vclass = r[q + 3 * C + 2], r[q + 3 * C + 3]
                dim = struct.unpack_from("<h", r, q + 3 * C + 4)[0]
                name, q = cstr(q + 3 * C + 6)
                dims = []
                for _ in range(dim):
                    dt, ds = struct.unpack_from("<h" + self.ufmt, r, q)
                    dims.append(ds)
                    q += 2 + C
                self.dbg_symbols.append(dict(addr=self.sval(addr), tag=tag, cs=cs, ce=ce,
                                             ident=ident, vclass=vclass, name=name, dims=dims))
            for _ in range(ntags):
                tid = struct.unpack_from("<h", r, q)[0]
                name, q = cstr(q + 2)
                self.dbg_tags[tid] = name
            self.has_debug = True
        except (struct.error, ValueError, IndexError):
            pass  # corrupt debug info -> ignore it

    # ---------------- strings ----------------
    def _charval(self, v, shift):
        if shift:
            if v & ((1 << shift) - 1):
                return None
            v >>= shift
        if 32 <= v < 256 and v != 127 or v in (9, 10, 13):
            return v
        return None

    def detect_shift(self):
        if self.forced_shift is not None:
            return self.forced_shift
        best, bestscore = 0, -1
        for sh in (0, 7, 8, 1, 2, 3, 4, 5, 6):
            score = 0
            run = 0
            for v in self.data_cells:
                if v and self._charval(v, sh) is not None:
                    run += 1
                else:
                    if run >= 4 and v == 0:
                        score += run
                    run = 0
            if score > bestscore * 1.5 + 50 or (bestscore < 0):
                best, bestscore = sh, score
        return best

    def find_strings(self):
        """Return {data_address: text} for every zero-terminated string."""
        sh = self.shift = self.detect_shift()
        res = {}
        cells = self.data_cells
        n = len(cells)
        i = 0
        while i < n:
            if cells[i] and self._charval(cells[i], sh) is not None:
                j = i
                chars = []
                while j < n and cells[j] and self._charval(cells[j], sh) is not None:
                    chars.append(chr(self._charval(cells[j], sh)))
                    j += 1
                if j < n and cells[j] == 0 and (j - i) >= 1:
                    res[i * self.cell] = "".join(chars)
                i = j + 1
            else:
                i += 1
        # packed strings (!"...") - 4 characters per cell, big-endian
        if self.cell == 4:
            i = 0
            while i < n:
                if i * 4 in res:
                    i += len(res[i * 4]) + 1
                    continue
                v = cells[i]
                bs = struct.pack(">I", v)
                if bs[0] >= 32 and all(32 <= b < 127 or b == 0 for b in bs) and bs[0] != 0:
                    out = bytearray()
                    j = i
                    ok = False
                    while j < n:
                        bs = struct.pack(">I", cells[j])
                        if 0 in bs:
                            k = bs.index(0)
                            if any(bs[k:]):
                                break
                            out += bs[:k]
                            ok = True
                            break
                        if not all(32 <= b < 127 for b in bs):
                            break
                        out += bs
                        j += 1
                    if ok and len(out) >= 4:
                        res[i * 4] = PACKED + out.decode("latin-1")
                        i = j + 1
                        continue
                i += 1
        return res

    # ---------------- disassembler ----------------
    def disassemble(self):
        cc = self.code_cells
        C = self.cell
        ins = []
        i = 0
        n = len(cc)
        while i < n:
            addr = i * C
            op = cc[i]
            if op >= len(OPCODES):
                ins.append((addr, "??? (0x%X)" % op, []))
                i += 1
                continue
            name, nops = OPCODES[op]
            if nops >= 0:
                ops = [self.sval(x) for x in cc[i + 1:i + 1 + nops]]
                i += 1 + nops
            elif name == "casetbl":
                cnt = cc[i + 1]
                ops = [self.sval(x) for x in cc[i + 1:i + 3 + 2 * cnt]]
                i += 3 + 2 * cnt
            else:  # file / symbol: size, ...
                sz = cc[i + 1]
                ops = [sz]
                i += 2 + sz // C
            ins.append((addr, name, ops))
        return ins
