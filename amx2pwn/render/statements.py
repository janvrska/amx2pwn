"""Rendering of statements."""

from ..amxfile import PACKED
from ..literals import pawn_str
from ..nodes import AddrOf, Assign, Call, Const, G, L, Prm, Raw, S


class StatementsMixin:
    """Rendering of statements."""

    def stmts(self, lst, ind, w, fi):
        for s in lst:
            self.stmt(s, ind, w, fi)

    def stmt(self, s, ind, w, fi):
        I = "    " * ind
        k = s.kind
        if k == "expr":
            e = s.e
            if isinstance(e, Assign) and isinstance(e.v, Raw) and e.v.text.startswith("/* lctrl ") \
                    and (isinstance(e.t, G) or (isinstance(e.t, L) and e.t.k is None)):
                # x = register (#emit LCTRL n) - the usual trick for getting the DAT/COD address
                n = e.v.text.split()[2]
                st = "stor.pri" if isinstance(e.t, G) else "stor.s.pri"
                w("%s#emit lctrl %s\n%s#emit %s %s\n" % (I, n, I, st, self.r(e.t)))
                return
            if isinstance(s.e, Call):
                w("%s%s;\n" % (I, self.call(s.e, 0)))
            else:
                w("%s%s;\n" % (I, self.r(s.e)))
        elif k == "decl":
            if s.arr and isinstance(s.init, Const) and self.is_literal(s.init) and hasattr(s, "init_n") \
                    and 0 <= s.init.v < len(self.d.a.data) and s.init.v % self.C == 0:
                b0 = s.init.v // self.C
                hv = [self.d.a.sval(x) for x in self.d.a.data_cells[b0:b0 + s.init_n // self.C]]
                if self.local_2d(s.loc, hv):
                    s.loc.dims = None
                    self.lit2d = True
            if s.arr and isinstance(s.init, Const) and (not self.is_literal(s.init) or getattr(self, "lit2d", False)) \
                    and 0 <= s.init.v < len(self.d.a.data) and s.init.v % self.C == 0:
                # data used to initialise a local array
                n = min(s.loc.size, getattr(s, "init_n", s.loc.size * self.C) // self.C)
                b = s.init.v // self.C
                vals = [self.d.a.sval(x) for x in self.d.a.data_cells[b:b + n]]
                self.lit2d = False
                two = self.local_2d(s.loc, vals)
                if two:
                    rows, cols = two
                    body = vals[rows:] + [0] * (rows * cols - len(vals[rows:]))
                    rs = [self.init1(body[r * cols:(r + 1) * cols])[3:] or "{0}" for r in range(rows)]
                    w("%snew %s%s[%d][%d] = {%s};\n" % (I, self.ltag(s.loc), s.loc.name, rows, cols, ", ".join(rs)))
                    return
                while vals and vals[-1] == 0:
                    vals.pop()
                w("%snew %s%s[%d]%s;\n" % (I, self.ltag(s.loc), s.loc.name, s.loc.size,
                                         (" = {%s}" % ", ".join(str(v) for v in vals)) if vals else ""))
            elif s.arr and self.is_literal(s.init) and hasattr(s, "init_n") \
                    and not self.lit_at(s.init.v).startswith(PACKED) \
                    and len(self.lit_at(s.init.v)) >= s.init_n // self.C:
                # old compiler: text without the terminating zero, the rest of the array is zero-filled
                n = s.init_n // self.C
                text = self.lit_at(s.init.v)[:n]
                self.str_used.add(s.init.v)
                if n < s.loc.size:
                    init = pawn_str(text)
                else:
                    init = "{%s}" % ", ".join(str(ord(ch)) for ch in text)
                w("%snew %s%s[%d] = %s;\n" % (I, self.ltag(s.loc), s.loc.name, s.loc.size, init))
            elif s.arr and not self.is_literal(s.init):
                w("%s%s;\n" % (I, self.decl_str(S("decl", loc=s.loc, init=None, arr=False))))
                w("%s%s = %s;\n" % (I, s.loc.name, self.arr(s.init)))
            else:
                w("%s%s;\n" % (I, self.decl_str(s)))
        elif k == "return":
            re_ = s.e.t if isinstance(s.e, AddrOf) else s.e
            if getattr(s, "arr", False) and isinstance(re_, Prm) and fi.addr not in self.used_value:
                # old compiler: returning an array parameter of unknown size (copies 0 bytes)
                w("%sreturn;\n" % I)
            elif getattr(s, "arr", False):
                w("%sreturn %s;\n" % (I, self.arr(s.e)))
            elif fi.ret_value or fi.addr in self.used_value:
                w("%sreturn %s;\n" % (I, self.r(s.e, 0, "f" if fi in self.float_ret else "v")))
            else:
                w("%sreturn;\n" % I)
        elif k == "if":
            self.if_stmt(s, ind, w, fi, I)
        elif k == "while":
            c = "true" if isinstance(s.c, Const) else self.r(s.c)
            w("%swhile (%s)\n%s{\n" % (I, c, I))
            self.stmts(s.body, ind + 1, w, fi)
            w("%s}\n" % I)
        elif k == "do":
            w("%sdo\n%s{\n" % (I, I))
            self.stmts(s.body, ind + 1, w, fi)
            w("%s}\n%swhile (%s);\n" % (I, I, self.r(s.c)))
        elif k == "for":
            init = self.decl_str(s.init) if s.init else ""
            inc = ", ".join(self.r(x.e) for x in s.inc if x.kind == "expr")
            other = [x for x in s.inc if x.kind != "expr"]
            c = self.r(s.c) if s.c is not None else ""
            w("%sfor (%s; %s; %s)\n%s{\n" % (I, init, c, inc, I))
            self.stmts(s.body, ind + 1, w, fi)
            if other:
                self.stmts(other, ind + 1, w, fi)
            w("%s}\n" % I)
        elif k == "switch":
            w("%sswitch (%s)\n%s{\n" % (I, self.r(s.e), I))
            for vals, is_def, body in s.cases:
                labels = []
                if vals:
                    labels.append("case %s:" % self.case_vals(vals))
                if is_def:
                    labels.append("default:")
                for lab in labels:
                    w("%s    %s\n" % (I, lab))
                w("%s    {\n" % I)
                self.stmts(body, ind + 2, w, fi)
                w("%s    }\n" % I)
            w("%s}\n" % I)
        elif k == "break":
            w("%sbreak;\n" % I)
        elif k == "continue":
            w("%scontinue;\n" % I)
        elif k == "goto":
            w("%sgoto l_%X;\n" % (I, s.t))
        elif k == "label":
            w("l_%X: {}\n" % s.t)
        elif k == "emit":
            w("%s%s\n" % (I, s.text))

    def if_stmt(self, s, ind, w, fi, I, prefix="if"):
        w("%s%s (%s)\n%s{\n" % (I, prefix, self.r(s.c), I))
        self.stmts(s.then, ind + 1, w, fi)
        w("%s}\n" % I)
        if s.els:
            if len(s.els) == 1 and s.els[0].kind == "if":
                self.if_stmt(s.els[0], ind, w, fi, I, "else if")
            else:
                w("%selse\n%s{\n" % (I, I))
                self.stmts(s.els, ind + 1, w, fi)
                w("%s}\n" % I)

    def case_vals(self, vals):
        out, k = [], 0
        while k < len(vals):
            j = k
            while j + 1 < len(vals) and vals[j + 1] == vals[j] + 1:
                j += 1
            if j - k >= 2:
                out.append("%d .. %d" % (vals[k], vals[j]))
            else:
                out.extend(str(v) for v in vals[k:j + 1])
            k = j + 1
        return ", ".join(out)

    def ltag(self, loc):
        return "Float:" if ("l", id(loc)) in self.F else ""

    def decl_str(self, s):
        loc = s.loc
        name = loc.name if loc.size == 1 else "%s[%d]" % (loc.name, loc.size)
        name = self.ltag(loc) + name
        if s.init is None:
            return "new %s" % name
        if isinstance(s.init, S):     # fill
            return "new %s = {%s, ...}" % (name, self.r(s.init.v))
        if s.arr:
            return "new %s = %s" % (name, self.arr(s.init))
        f = self.ltag(loc) or self.floatish(s.init)
        return "new %s = %s" % (name, self.r(s.init, 2, "f" if f else "v"))
