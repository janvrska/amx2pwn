"""Rendering of expressions."""

from ..literals import char_lit, fmt_float_bits, nice_int, pawn_str
from ..nodes import (
    AddrOf, Assign, Bin, Call, CharAt, CMP_OPS, Const, Deref, Elem, FOPS, G, HeapTmp, IA, L,
    OVL_OPS, PostInc, PREC, Prm, Raw, Row, Tern, Un,
)


class ExpressionsMixin:
    """Rendering of expressions."""

    def r(self, e, prec=0, mode="v"):
        if mode == "a":
            return self.arr(e)
        if mode in ("r", "va"):
            return self.ref(e, mode == "va")
        if isinstance(e, Const):
            v = e.v
            if mode == "f":
                fs = fmt_float_bits(v)
                if fs is not None:
                    return fs if not fs.startswith("-") or prec <= 13 else "(%s)" % fs
            if mode == "ch":
                cl = char_lit(v)
                if cl is not None:
                    return cl
            ni = nice_int(v)
            if ni is not None:
                return ni
            if v < 0 and prec > 13:
                return "(%d)" % v
            return str(v)
        if isinstance(e, G):
            return self.gvar(e.addr)
        if isinstance(e, Prm):
            return self.pname(e.f, e.k)
        if isinstance(e, L):
            return e.loc.name if e.k is None else "%s[%d]" % (e.loc.name, e.k)
        if isinstance(e, AddrOf):
            return self.r(e.t, prec)
        if isinstance(e, (IA, Elem)):
            ia = e if isinstance(e, IA) else e.ia
            base, idx = ia.base, ia.idx
            # array inside a row (enum record): g[i][43][k] -> g[i][43 + k]
            while isinstance(base, IA):
                idx = Bin("+", base.idx, idx)
                base = base.base
            return "%s[%s]" % (self.arr(base, lit=False), self.r(idx))
        if isinstance(e, Row):
            self.mark_row(e)
            return self.r(e.x, prec)
        if isinstance(e, CharAt):
            return "%s{%s}" % (self.arr(e.base, lit=False), self.r(e.idx))
        if isinstance(e, Deref):
            return "%s[0]" % self.r(e.a, 15)
        if isinstance(e, HeapTmp):
            return self.r(e.content, prec, mode) if e.content is not None else "0"
        if isinstance(e, Raw):
            return e.text
        if isinstance(e, Un) and e.op == "fneg":
            self.ops_used.add("neg")
            s = "-" + self.fa(e.a, 14)
            return s if prec <= 14 else "(%s)" % s
        if isinstance(e, Un) and e.op == "!" and self.is_fcmp(e.a):
            return self.r(Bin("==", e.a, Const(0)), prec)
        if isinstance(e, Un):
            if e.op == "-" and self.ftag(e.a):
                s = "-_:" + self.r(e.a, 15)
            else:
                s = e.op + self.r(e.a, 14)
            return s if prec <= 14 else "(%s)" % s
        if isinstance(e, Bin) and e.op in CMP_OPS and isinstance(e.a, Const) and not isinstance(e.b, Const):
            e = Bin({"<": ">", ">": "<", "<=": ">=", ">=": "<="}.get(e.op, e.op), e.b, e.a)
        if isinstance(e, Bin) and e.op in CMP_OPS and isinstance(e.b, Const) and self.is_char(e.a) \
                and char_lit(e.b.v) is not None:
            p = PREC[e.op]
            s = "%s %s %s" % (self.r(e.a, p), e.op, self.r(e.b, p + 1, "ch"))
            return s if prec <= p else "(%s)" % s
        if isinstance(e, Bin) and e.op in CMP_OPS and self.is_fcmp(e.a) and isinstance(e.b, Const) and e.b.v == 0:
            # floatcmp(a, b) > 0  ->  a > b
            self.ops_used.add("cmp")
            p = PREC[e.op]
            s = "%s %s %s" % (self.fa(e.a.args[0], p + 1), e.op, self.fa(e.a.args[1], p + 1))
            return s if prec <= p else "(%s)" % s
        if isinstance(e, Bin):
            p = PREC[e.op]
            # integer operation on a Float value: keep the _: tag so the meaning is unchanged and visible
            cast = e.op in OVL_OPS and (self.ftag(e.a) or self.ftag(e.b))
            la = self.ia_cast(e.a, p, cast)
            if e.op in ("&&", "||", "+", "*", "&", "|", "^") and isinstance(e.b, Bin) and e.b.op == e.op:
                rb = self.ia_cast(e.b, p, cast)
            else:
                rb = self.ia_cast(e.b, p + 1, cast)
            if e.op in CMP_OPS:
                if isinstance(e.a, Bin) and e.a.op in CMP_OPS:
                    la = "(%s)" % self.r(e.a)
                if isinstance(e.b, Bin) and e.b.op in CMP_OPS:
                    rb = "(%s)" % self.r(e.b)
            s = "%s %s %s" % (la, e.op, rb)
            return s if prec <= p else "(%s)" % s
        if isinstance(e, Tern):
            s = "%s ? %s : %s" % (self.r(e.c, 4), self.r(e.a, 4, mode), self.r(e.b, 3, mode))
            return s if prec <= 3 else "(%s)" % s
        if isinstance(e, PostInc):
            return self.r(e.t, 15) + e.op
        if isinstance(e, Assign):
            s = self.assign_str(e)
            return s if prec <= 2 else "(%s)" % s
        if isinstance(e, Call):
            if self.template_of(e) is not None:
                return self.r(self.expand(e), prec, mode)
            if e.native and e.name in FOPS and len(e.args) == 2:
                op = FOPS[e.name]
                self.ops_used.add(op)
                p = PREC[op]
                s = "%s %s %s" % (self.fa(e.args[0], p), op, self.fa(e.args[1], p + 1))
                return s if prec <= p else "(%s)" % s
            if e.native and e.name == "float" and len(e.args) == 1 and isinstance(e.args[0], Const) \
                    and abs(e.args[0].v) < 10000000:
                return self.fa(e, prec)
            if not e.native and e.faddr in self.d.fby:
                self.used_value.add(e.faddr)
            return self.call(e, prec)
        return "/*?%s*/" % type(e).__name__

    def is_fcmp(self, x):
        if isinstance(x, Call) and self.template_of(x) is not None:
            return False
        return isinstance(x, Call) and x.native and x.name == "floatcmp" and len(x.args) == 2

    def assign_str(self, e):
        if e.arr:
            return "%s = %s" % (self.arr(e.t, lit=False), self.arr(e.v))
        t = self.r(e.t, 15)
        v = e.v
        if isinstance(v, Const) and self.is_char(e.t) and char_lit(v.v) is not None:
            return "%s = %s" % (t, self.r(v, 2, "ch"))
        tf = self.ftag(e.t)
        if tf:
            return "%s = %s" % (t, self.r(v, 2, "f"))
        if isinstance(v, Bin) and v.op in ("+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", ">>>") \
                and self.r(v.a, 15) == t:
            if v.op in ("+", "-") and isinstance(v.b, Const) and v.b.v == 1:
                return t + v.op * 2
            return "%s %s= %s" % (t, v.op, self.r(v.b, 2))
        if isinstance(v, Bin) and v.op in ("+", "*", "&", "|", "^") and self.r(v.b, 15) == t:
            if v.op == "+" and isinstance(v.a, Const) and v.a.v == 1:
                return t + "++"
            return "%s %s= %s" % (t, v.op, self.r(v.a, 2))
        return "%s = %s" % (t, self.r(v, 2, "f" if self.floatish(v) else "v"))

    def floatish(self, v):
        if isinstance(v, Const):
            fs = fmt_float_bits(v.v)
            return fs is not None and abs(v.v) > 0x100000 and abs(v.v) < 0x7F000000 and \
                not (abs(v.v) & 0xFF == 0xFF)
        return False

    def arr(self, e, lit=True):
        d = self.d
        if isinstance(e, Bin) and e.op == "+" and isinstance(e.b, Const) and e.b.v % self.C == 0 \
                and isinstance(e.a, (Prm, AddrOf, Row, Const)):
            return "%s[%d]" % (self.arr(e.a, False), e.b.v // self.C)
        if isinstance(e, Const):
            v = e.v
            if v % self.C or not (0 <= v < len(d.a.data)):
                return self.r(e)
            t = self.lit_at(v) if lit else None
            if t is not None:
                self.str_used.add(v)
                return pawn_str(t)
            if v not in d.g_arr:
                d.g_arr[v] = 0
                self.marks_changed = True
            if self.layout_ready and self.owner(v) == v:
                return self.gname(v)
            return self.gvar(v)
        if isinstance(e, AddrOf):
            t = e.t
            if isinstance(t, Const):
                return self.arr(t, lit)
            if isinstance(t, L):
                return t.loc.name if t.k in (None, 0) or t.loc.size == 1 else "%s[%d]" % (t.loc.name, t.k)
            if isinstance(t, Prm):
                return self.pname(t.f, t.k)
            return self.r(t)
        if isinstance(e, Prm):
            if e.f.pkind.get(e.k) not in ("a", "r"):
                e.f.pkind[e.k] = "a"
                self.marks_changed = True
            return self.pname(e.f, e.k)
        if isinstance(e, HeapTmp):
            return self.arr(e.content, lit) if e.content is not None else "0"
        if isinstance(e, Row):
            self.mark_row(e)
            return self.r(e.x)
        if isinstance(e, L):
            return e.loc.name if e.k is None else "%s[%d]" % (e.loc.name, e.k)
        return self.r(e, 15)

    def ref(self, e, variadic):
        d = self.d
        if isinstance(e, Bin) and e.op == "+" and isinstance(e.b, Const) and e.b.v % self.C == 0 \
                and isinstance(e.a, (Prm, AddrOf, Row, Const)):
            return self.arr(e)
        if isinstance(e, AddrOf):
            t = e.t
            if variadic and isinstance(t, L) and t.loc.size > 1 and not t.loc.dims and t.k in (None, 0):
                # whole local array as a variadic argument: 'name' instead of 'name[0]'
                # (both push the same address)
                return t.loc.name
            return self.r(e.t)
        if isinstance(e, Const):
            v = e.v
            t = self.lit_at(v)
            if t is not None and t != "":
                self.str_used.add(v)
                return pawn_str(t)
            if 0 <= v < len(d.a.data):
                # a reference is always a variable, never a string
                d.g_scalar.add(v)
                return self.gvar(v)
            return self.r(e)
        if isinstance(e, HeapTmp):
            if e.content is None:
                return "0"
            return self.r(e.content, 0, "f" if self.floatish(e.content) else "v")
        if isinstance(e, Prm):
            return self.pname(e.f, e.k)
        if isinstance(e, Row):
            # reference to the first cell of a 2D array row: g[i] -> g[i][0]
            return self.r(e) + "[0]"
        if isinstance(e, IA):
            return self.r(e)
        if isinstance(e, L) and e.loc.size > 1:
            return self.r(e)
        return self.r(e)

    def call(self, c, prec):
        modes = self.modes_for(c)
        args = []
        fi = None if c.native else self.d.fby.get(c.faddr)
        for i, x in enumerate(c.args):
            m = modes[i] if i < len(modes) else (modes[-1] if modes and modes[-1] == "va" else "v")
            if fi is not None and m == "v" and self.looks_array(x, strong=True):
                fi.pkind[i] = "a"
                self.marks_changed = True
                m = "a"
            args.append(self.r(x, 0, m))
        args = self.nice_args(c, args)
        return "%s(%s)" % (c.name, ", ".join(args))

    def is_empty_str(self, v):
        """Literal "" = a single zero cell that nothing else refers to."""
        d, C = self.d, self.C
        if v in d.g_arr or v in d.g_scalar or not (0 <= v < len(d.a.data)) or v % C:
            return False
        if d.a.data_cells[v // C] != 0:
            return False
        # another literal starts right after ""; zeroed global arrays are followed by more zeros
        k = v // C
        if k + 1 < len(d.a.data_cells) and d.a.data_cells[k + 1] == 0:
            return False
        if v == 0:
            return True
        # "" sits right after the end of another string or after another zero
        return d.a.data_cells[(v - C) // C] == 0

    def is_literal(self, e):
        d = self.d
        if isinstance(e, Const):
            v = e.v
            return self.lit_at(v) is not None
        return False

    def lit_at(self, v):
        """Text of the string literal at address v (or None)."""
        d, C = self.d, self.C
        if v in d.g_arr or v in d.g_scalar or v % C or not (0 <= v < len(d.a.data)):
            return None
        if v in d.strings:
            return d.strings[v]
        if self.is_empty_str(v):
            return ""
        cells = d.a.data_cells
        k = v // C
        out = []
        while k < len(cells) and cells[k] != 0:
            c = cells[k]
            if not (32 <= c < 256 or c in (9, 10, 13)):
                return None
            out.append(chr(c))
            k += 1
        if not out or k >= len(cells):
            return None
        return "".join(out)

    def looks_array(self, x, strong=False):
        d = self.d
        if isinstance(x, Const):
            if strong:
                return False
            return (x.v in d.strings and x.v >= 0x100 and x.v not in d.g_scalar) or \
                    (x.v >= 0x100 and self.is_empty_str(x.v))
        if isinstance(x, AddrOf):
            return isinstance(x.t, L) and x.t.loc.size > 1
        if isinstance(x, Bin) and x.op == "+" and isinstance(x.b, Const) and isinstance(x.a, Prm):
            return x.a.f.pkind.get(x.a.k) == "a"
        if isinstance(x, Row):
            return True
        return isinstance(x, Prm) and x.f.pkind.get(x.k) == "a"

    def modes_for(self, c):
        d = self.d
        if c.native:
            if c.name in d.natdb:
                out = []
                letters = d.natdb[c.name][0]
                cnts = d.arg_counts.get(c.name)
                if cnts and "m" not in letters:
                    letters = (list(letters) + ["i"] * max(cnts))[:max(cnts)]
                for t in letters:
                    out.append({"s": "a", "r": "r", "fr": "r", "f": "f", "m": "va"}.get(t, "v"))
                return out
            return self.infer_native(c.name)
        fi = d.fby.get(c.faddr)
        if not fi:
            return []
        return [{"a": "a", "r": "r"}.get(fi.pkind.get(k),
                                         "f" if ("p", id(fi), k) in self.F else "v") for k in range(fi.nparams)]

    def infer_native(self, name):
        if name in self.nat_inf:
            return self.nat_inf[name]
        d = self.d
        modes = {}
        counts = d.arg_counts.get(name, set())
        for c in self.calls_by_native.get(name, []):
            for i, x in enumerate(c.args):
                k = None
                if isinstance(x, HeapTmp):
                    k = "va"
                elif isinstance(x, Const) and x.v in d.strings and x.v >= 0x100:
                    k = "a"
                elif isinstance(x, AddrOf):
                    k = "a" if isinstance(x.t, L) and x.t.loc.size > 1 else "r"
                elif isinstance(x, Prm) and x.f.pkind.get(x.k) in ("a", "r"):
                    k = "a" if x.f.pkind.get(x.k) == "a" else "r"
                elif isinstance(x, Row):
                    k = "a"
                if k and modes.get(i) != "va":
                    modes[i] = k
        n = max(counts) if counts else 0
        out = [modes.get(i, "v") for i in range(n)]
        if len(counts) > 1:
            m = min(counts)
            out = out[:m] + ["va"] * (n - m)
        if "va" in out:
            f = out.index("va")
            out = out[:f] + ["va"] * (len(out) - f)
        self.nat_inf[name] = out
        return out

    def pname(self, f, k):
        return f.pnames.get(k, "arg%d" % k)
