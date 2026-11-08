"""Layout of global variables: 1D, 2D, ragged and 3D arrays."""

import bisect

from ..literals import pawn_str
from ..nodes import AddrOf, Const, Elem, G, L, N, Prm, Row, iter_nodes, stmt_roots


class LayoutMixin:
    """Layout of global variables: 1D, 2D, ragged and 3D arrays."""

    def finalize_layout(self):
        d, a, C = self.d, self.d.a, self.C
        starts = sorted(set(d.g_arr) | d.g_scalar | set(self.str_used))
        info = {}
        datalen = len(a.data)
        end2d = -1
        for s0 in sorted(d.g_arr):
            if not (0 <= s0 < datalen) or s0 < end2d:
                continue
            nxt = [x for x in starts if x > s0]
            gap = ((nxt[0] if nxt else datalen) - s0) // C
            base = s0 // C
            hdr0 = a.data_cells[base] if base < len(a.data_cells) else 0
            # 2D: header with row offsets
            rows = hdr0 // C if hdr0 % C == 0 else 0
            two = None
            if (1 < rows <= 100000 or (rows == 1 and s0 in self.row_bases)) and base + rows <= len(a.data_cells):
                offs = [a.data_cells[base + r] + (base + r) * C for r in range(rows)]
                if offs[0] == (base + rows) * C and all(offs[r + 1] > offs[r] for r in range(rows - 1)):
                    lens = [(offs[r + 1] - offs[r]) // C for r in range(rows - 1)]
                    if lens and len(set(lens)) == 1:
                        two = (rows, lens[0])
                    elif not lens:
                        two = (rows, max(1, gap - rows))
                    elif d.g_arr[s0] in (0, rows):
                        # last row: up to the end of the string (including the terminator)
                        k = offs[-1] // C
                        cells = a.data_cells
                        while k < len(cells) and cells[k] != 0:
                            k += 1
                        last = k + 1 - offs[-1] // C
                        ragged = lens + [last]
                        info[s0] = ("2dr", rows, ragged)
                        end2d = s0 + self.gsize_of(info[s0]) * C
                        continue
            three = self.detect_3d(base, two) if two else None
            if three:
                info[s0] = ("3d",) + three
                end2d = s0 + self.gsize_of(info[s0]) * C
            elif two and (d.g_arr[s0] in (0, two[0])):
                info[s0] = ("2d", two[0], two[1])
                end2d = s0 + two[0] * (two[1] + 1) * C
            else:
                size = d.g_arr[s0] or gap
                info[s0] = ("1d", max(1, size))
        self.ginfo = info
        self.ranges = sorted((s, s + self.gsize(s) * C) for s in info)
        self.rstarts = [r[0] for r in self.ranges]

    def local_2d(self, loc, vals):
        """Local 2D array: the data starts with a header of row offsets."""
        C = self.C
        if not vals or vals[0] % C or vals[0] <= C:
            return None
        rows = vals[0] // C
        if rows > len(vals) or (loc.size - rows) % rows:
            return None
        cols = (loc.size - rows) // rows
        for r in range(rows):
            if vals[r] != (rows - r + r * cols) * C:
                return None
        loc.dims = (rows, cols)
        return rows, cols

    def local_ragged(self, loc, vals):
        """Local 2D array with rows of different length, e.g. new reasons[][] = {"Quit", "Kick"}.
        Returns the rows as Pawn strings, or None."""
        C = self.C
        if not vals or vals[0] % C or vals[0] <= C:
            return None
        rows = vals[0] // C
        if rows >= len(vals):
            return None
        starts = [vals[r] // C + r for r in range(rows)] + [loc.size]
        if starts[0] != rows or any(starts[r + 1] <= starts[r] for r in range(rows)):
            return None
        out = []
        for r in range(rows):
            cells = vals[starts[r]:starts[r + 1]]
            k = 0
            while k < len(cells) and cells[k] and (32 <= cells[k] < 256 or cells[k] in (9, 10, 13)):
                k += 1
            if any(cells[k:]) or (r < rows - 1 and k >= len(cells)):
                return None
            out.append(pawn_str("".join(chr(v) for v in cells[:k])))
        loc.dims = (rows, 0)
        return out

    def mark_row(self, e):
        """X[0][i]: row 0 of a 2D array is read straight from the header (G) - the start of the array."""
        if isinstance(e.x, G) and not self.layout_ready:
            self.row_bases.add(e.x.addr)
            if e.x.addr not in self.d.g_arr:
                self.d.g_arr[e.x.addr] = 0
                self.marks_changed = True

    def detect_3d(self, base, two):
        """g[a][b][c]: the row header (a cells) is followed by a second-level header (a*b cells)."""
        cells, C = self.d.a.data_cells, self.C
        a, b = two
        h2 = base + a
        n2 = a * b
        if b < 1 or h2 + n2 + 1 > len(cells):
            return None
        data0 = h2 + n2
        d0 = cells[h2] + h2 * C
        if d0 != data0 * C:
            return None
        if n2 > 1:
            d1 = cells[h2 + 1] + (h2 + 1) * C
            if (d1 - d0) % C or d1 <= d0:
                return None
            c = (d1 - d0) // C
        else:
            return None
        if data0 + n2 * c > len(cells):
            return None
        for j in range(n2):
            if cells[h2 + j] + (h2 + j) * C != (data0 + j * c) * C:
                return None
        return (a, b, c)

    def arr_dims(self, x):
        """Number of dimensions of the array an expression refers to (1 = plain array)."""
        if isinstance(x, Const):
            inf = self.ginfo.get(x.v) if self.layout_ready else None
            if inf and self.owner(x.v) == x.v:
                return {"1d": 1, "2d": 2, "2dr": 2, "3d": 3}[inf[0]]
            return 1
        if isinstance(x, G):
            own = self.owner(x.addr)
            if own is not None and own == x.addr:
                inf = self.ginfo[own]
                return {"1d": 1, "2d": 2, "2dr": 2, "3d": 3}[inf[0]]
            return 1
        if isinstance(x, AddrOf) and isinstance(x.t, L):
            return 2 if x.t.loc.dims else 1
        if isinstance(x, Prm):
            return getattr(x.f, "pdims", {}).get(x.k, 1)
        if isinstance(x, Row):
            inner = x.x
            base = None
            if isinstance(inner, Elem):
                base = inner.ia.base
            elif isinstance(inner, G):
                base = inner
            if base is None:
                return 1
            return max(1, self.arr_dims(base) - 1)
        return 1

    def infer_pdims(self):
        d = self.d
        for fi in d.funcs:
            fi.pdims = {}
            # arg[i][j] inside the function itself: a 2D parameter even without callers
            for e in self._body_nodes(fi.body):
                if isinstance(e, Row) and isinstance(e.x, Elem) and isinstance(e.x.ia.base, Prm) \
                        and e.x.ia.base.f is fi:
                    fi.pdims[e.x.ia.base.k] = max(fi.pdims.get(e.x.ia.base.k, 1), 2)
        for _ in range(4):
            changed = False
            for c in self.all_calls:
                if c.native or c.faddr not in d.fby:
                    continue
                fi = d.fby[c.faddr]
                for k, x in enumerate(c.args):
                    if fi.pkind.get(k) != "a":
                        continue
                    n = self.arr_dims(x)
                    if n > fi.pdims.get(k, 1):
                        fi.pdims[k] = n
                        changed = True
            if not changed:
                break

    @staticmethod
    def _body_nodes(stmts):
        """All expression nodes of a statement list."""
        todo = list(stmts)
        while todo:
            s = todo.pop()
            if s is None:
                continue
            for root in stmt_roots(s):
                yield from iter_nodes(root)
            for sub in ("then", "els", "body", "inc"):
                v = getattr(s, sub, None)
                if isinstance(v, list):
                    todo.extend(v)
            if s.kind == "for" and getattr(s, "init", None) is not None and not isinstance(s.init, N):
                todo.append(s.init)
            if s.kind == "switch":
                for _, _, b in s.cases:
                    todo.extend(b)

    def ragged_pos(self, inf, k):
        k -= inf[1]
        for r, n in enumerate(inf[2]):
            if k < n:
                return r, k
            k -= n
        return len(inf[2]) - 1, k

    def gsize_of(self, i):
        if i[0] == "2dr":
            return i[1] + sum(i[2])
        if i[0] == "3d":
            return i[1] + i[1] * i[2] + i[1] * i[2] * i[3]
        return i[1] if i[0] == "1d" else i[1] * (i[2] + 1)

    def gsize(self, s):
        i = self.ginfo[s]
        return self.gsize_of(i)

    def owner(self, addr):
        k = bisect.bisect_right(self.rstarts, addr) - 1
        if k >= 0 and self.ranges[k][0] <= addr < self.ranges[k][1]:
            return self.ranges[k][0]
        return None

    def gname(self, s):
        gn = getattr(self, "gnames", None)
        if gn and s in gn:
            return gn[s]
        for adr, name in self.d.a.pubvar_list:
            if adr == s:
                return name
        for sym in self.d.a.dbg_symbols:
            if sym["ident"] != 9 and sym["vclass"] in (0, 2) and sym["addr"] == s and sym["cs"] == 0:
                return sym["name"]
        return "g_%X" % s

    def gvar(self, addr):
        own = self.owner(addr) if self.layout_ready else None
        if own is None:
            self.d.g_scalar.add(addr)
            return self.gname(addr)
        k = (addr - own) // self.C
        inf = self.ginfo[own]
        if inf[0] == "2dr":
            if k < inf[1]:
                return "%s[%d]" % (self.gname(own), k)
            r, c = self.ragged_pos(inf, k)
            return "%s[%d][%d]" % (self.gname(own), r, c)
        if inf[0] == "3d":
            a3, b3, c3 = inf[1], inf[2], inf[3]
            if k < a3:
                return "%s[%d]" % (self.gname(own), k)
            if k < a3 + a3 * b3:
                r, j = divmod(k - a3, b3)
                return "%s[%d][%d]" % (self.gname(own), r, j)
            r, rem = divmod(k - a3 - a3 * b3, b3 * c3)
            j, z = divmod(rem, c3)
            return "%s[%d][%d][%d]" % (self.gname(own), r, j, z)
        if inf[0] == "2d":
            rows, cols = inf[1], inf[2]
            if k >= rows:
                r, c = divmod(k - rows, cols)
                return "%s[%d][%d]" % (self.gname(own), r, c)
            return "%s[%d]" % (self.gname(own), k)
        return "%s[%d]" % (self.gname(own), k)
