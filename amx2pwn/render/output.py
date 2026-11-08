"""Whole-file rendering: naming passes, declarations, globals."""

import io

from ..amxfile import PACKED
from ..libraries import PAWN_KEYWORDS
from ..literals import pawn_str
from ..natives import CORE, ENUMS, NATIVE_PNAMES
from ..nodes import AddrOf, Assign, Call, Const, N, Prm, S


def strip_zeros(vals):
    """vals without the trailing zeros."""
    n = len(vals)
    while n and vals[n - 1] == 0:
        n -= 1
    return vals[:n]


class OutputMixin:
    """Whole-file rendering: naming passes, declarations, globals."""

    def render(self, out, srcname, func_filter=None):
        d, a = self.d, self.d.a
        self.calls_by_native = {}
        acc = []
        for fi in d.funcs:
            self._calls(fi.body, acc)
        for c in acc:
            if c.native:
                self.calls_by_native.setdefault(c.name, []).append(c)
            elif c.faddr in d.fby:
                fi = d.fby[c.faddr]
                fi.nparams = max(fi.nparams, len(c.args))
        self.all_calls = acc
        self.auto_names(acc)
        self.detect_float_ops()
        self.identify_libs()
        self.strarrs = set()
        self.enums_used = set()
        # pass 1 collects marks (array / reference), the final pass renders
        self.layout_ready = False
        self.str_used = set()
        self.row_bases = set()
        # repeat until the propagation of marks (array / reference) between functions settles
        for npass in range(8):
            self.nat_inf = {}
            self.used_value = set()
            self.marks_changed = False
            sink = io.StringIO()
            for fi in d.funcs:
                self.function(fi, sink.write)
            if npass >= 1 and not self.marks_changed:
                break
        self.finalize_layout()
        self.layout_ready = True
        self.infer_pdims()
        self.infer_floats()
        self.infer_const()
        self.name_globals()
        self.find_strarrs()
        reserved = {fi.name for fi in d.funcs} | set(d.native_names) | PAWN_KEYWORDS
        reserved |= {self.gname(x) for x in set(self.ginfo) | set(d.g_scalar)}
        for fi in d.funcs:
            self.name_locals(fi, reserved)
        self.enums_used = set()
        self.nat_inf = {}
        self.ops_used = set()
        body = io.StringIO()
        for fi in d.funcs:
            self.function(fi, body.write)
        w = out.write
        w("// ==========================================================\n")
        w("//  Decompiled from: %s   (amx2pwn)\n" % srcname)
        w("//  Variable and function names without debug info are generated.\n")
        w("//  Compile without a_samp/float.inc - natives and float operators are declared below.\n")
        w("// ==========================================================\n\n")
        w("#pragma rational Float\n")
        w("#pragma tabsize 0\n")
        dyn = (a.stp - a.hea) // self.C
        if dyn > 0:
            w("#pragma dynamic %d\n" % dyn)
        w("\n")
        self.write_natives(w)
        self.write_float_ops(w)
        self.write_globals(w)
        w("// ---------------------------------------------------------- forwards\n")
        for fi in d.funcs:
            if fi.public:
                w("forward %s%s(%s);\n" % ("Float:" if fi in self.float_ret else "", fi.name, self.params(fi)))
        w("\n")
        w(body.getvalue())
        self.write_call_stubs(w)

    def write_call_stubs(self, w):
        """Calls into code that is not a normal function (no 'proc' there, typically an
        anti-decompiler trick): declare an empty function so the output still compiles."""
        nargs = {}
        for c in self.all_calls:
            if not c.native and c.faddr not in self.d.fby:
                nargs.setdefault((c.faddr, c.name), set()).add(len(c.args))
        for (addr, name), cnts in sorted(nargs.items()):
            ps = ", ".join("arg%d" % i for i in range(max(cnts)))
            w("// The code at 0x%X is not a normal function (see the .asm listing).\n" % addr)
            w("stock %s(%s)\n{\n" % (name, ps))
            if ps:
                w("    #pragma unused %s\n" % ps)
            w("    return 0;\n}\n\n")

    def auto_names(self, calls):
        """Name functions after dcmd(...) and parameters after how natives use them."""
        d = self.d
        used = {fi.name for fi in d.funcs} | set(d.native_names)
        # dcmd_xxx: the condition contains strcmp(cmdtext[1], "xxx", ...) and a call to a script function
        cand = {}
        conds = []
        for fi in d.funcs:
            self._conds(fi.body, conds)
        for c in conds:
            cs = []
            self._calls([S("expr", e=c)], cs)
            names = [x.args[1].v for x in cs if x.native and x.name == "strcmp" and len(x.args) > 1
                     and isinstance(x.args[1], Const) and x.args[1].v in d.strings]
            if len(names) != 1:
                continue
            txt = d.strings[names[0]]
            ident = "".join(ch if ch.isalnum() and ord(ch) < 128 else "_" for ch in txt)
            if not ident or ident[0].isdigit():
                continue
            for x in cs:
                if not x.native and x.faddr in d.fby:
                    cand.setdefault(x.faddr, set()).add("dcmd_" + ident)
        for fa, names in cand.items():
            fi = d.fby[fa]
            if len(names) == 1 and fi.name.startswith("func_"):
                nm = names.pop()
                if nm not in used:
                    used.add(nm)
                    fi.name = nm
                    for c in calls:
                        if not c.native and c.faddr == fa:
                            c.name = nm
                    fi.pnames.setdefault(0, "playerid")
                    fi.pnames.setdefault(1, "params")
        # functions returning an array: hidden last parameter = return buffer
        by_name = {t.lstrip(PACKED) for t in d.strings.values()}
        for fi in d.funcs:
            cnts = d.arg_counts.get(fi.name)
            if not cnts and fi.nparams > 0 and fi.name not in d.cbdb and fi.name not in by_name:
                # function nobody calls: the hidden buffer can only be the last parameter
                cnts = {fi.nparams - 1}
            if not cnts or len(cnts) != 1:
                continue
            # public returning an array (old compilers allowed it): only when it is not called by name
            if fi.public and (fi.name in d.cbdb or fi.name in by_name):
                continue
            n = cnts.pop()
            cnts.add(n)
            if fi.nparams == n + 1 and self._fix_ret_array(fi, fi.body, n):
                fi.nparams = n
                fi.ret_value = True
                fi.pkind.pop(n, None)
                fi.public = False
        # script function parameter that only ever receives strings -> array
        sites = {}
        for c in calls:
            if not c.native and c.faddr in d.fby:
                for i, x in enumerate(c.args):
                    sites.setdefault((c.faddr, i), []).append(x)
        for (fa, i), xs in sites.items():
            if i in d.fby[fa].used_params:
                continue
            if all(isinstance(x, Const) and self.looks_array(x) for x in xs):
                d.fby[fa].pkind.setdefault(i, "a")
        for fa in cand:
            if d.fby[fa].name.startswith("dcmd_"):
                d.fby[fa].pkind.setdefault(1, "a")
        # parameters: what is passed to a native as a player / vehicle
        role = {"p": "playerid", "v": "vehicleid", "o": "objectid"}
        for fi in d.funcs:
            if fi.public and fi.name in d.cbdb:
                continue
            cs = []
            self._calls(fi.body, cs)
            sugg = {}
            for c in cs:
                if not c.native or c.name not in d.natdb:
                    continue
                letters = d.natdb[c.name][0]
                for i, x in enumerate(c.args):
                    if i < len(letters) and letters[i] in role and isinstance(x, Prm) and x.f is fi:
                        sugg.setdefault(role[letters[i]], set()).add(x.k)
            for nm, ks in sugg.items():
                if len(ks) == 1:
                    k = ks.pop()
                    if k not in fi.pnames and nm not in fi.pnames.values():
                        fi.pnames[k] = nm

    def _fix_ret_array(self, fi, stmts, n):
        found = False
        k = 0
        while k < len(stmts):
            s0 = stmts[k]
            e = getattr(s0, "e", None)
            if s0.kind == "expr" and isinstance(e, Assign) and e.arr and isinstance(e.t, Prm) \
                    and e.t.f is fi and e.t.k == n and k + 1 < len(stmts) and stmts[k + 1].kind == "return":
                stmts[k + 1].e = AddrOf(e.v) if not isinstance(e.v, AddrOf) else e.v
                stmts[k + 1].arr = True
                del stmts[k]
                found = True
                continue
            for sub in ("then", "els", "body"):
                v = getattr(s0, sub, None)
                if isinstance(v, list) and self._fix_ret_array(fi, v, n):
                    found = True
            if s0.kind == "switch":
                for _, _, b in s0.cases:
                    if self._fix_ret_array(fi, b, n):
                        found = True
            k += 1
        return found

    def _conds(self, stmts, acc):
        for s in stmts:
            if s.kind in ("if", "while", "do", "for") and getattr(s, "c", None) is not None:
                acc.append(s.c)
            for sub in ("then", "els", "body", "inc"):
                v = getattr(s, sub, None)
                if isinstance(v, list):
                    self._conds(v, acc)
            if s.kind == "switch":
                for _, _, b in s.cases:
                    self._conds(b, acc)

    def _calls(self, stmts, acc):
        def walk(e):
            if e is None or not isinstance(e, N):
                return
            if isinstance(e, Call):
                acc.append(e)
            for k in e.kids():
                walk(k)
        for s in stmts:
            for attr in ("e", "c", "init"):
                v = getattr(s, attr, None)
                if isinstance(v, N):
                    walk(v)
            for sub in ("then", "els", "body", "inc"):
                v = getattr(s, sub, None)
                if isinstance(v, list):
                    self._calls(v, acc)
            if s.kind == "for" and s.init is not None:
                self._calls([s.init], acc)
            if s.kind == "switch":
                for _, _, b in s.cases:
                    self._calls(b, acc)

    def variadic(self, fi):
        """Function with a variable number of arguments (uses numargs/getarg/setarg)."""
        if not hasattr(fi, "_variadic"):
            cs = []
            self._calls(fi.body, cs)
            fi._variadic = not fi.public and any(
                c.native and c.name in ("numargs", "getarg", "setarg") for c in cs)
        return fi._variadic

    def params(self, fi):
        ps = []
        n = fi.nparams
        if self.variadic(fi):
            n = max(fi.used_params) + 1 if fi.used_params else 0
        for k in range(n):
            nm = self.pname(fi, k)
            kd = fi.pkind.get(k)
            if ("p", id(fi), k) in self.F:
                nm = "Float:" + nm
            if kd == "a" and (id(fi), k) not in getattr(self, "nonconst", {(id(fi), k)}) \
                    and not (fi.public and fi.name in self.d.cbdb):
                nm = "const " + nm
            dims = getattr(fi, "pdims", {}).get(k, 1)
            if kd == "a" and dims == 1 and fi.psize.get(k):
                ps.append("%s[%d]" % (nm, fi.psize[k]))
            else:
                ps.append(("%s%s" % (nm, "[]" * dims)) if kd == "a" else ("&%s" % nm) if kd == "r" else nm)
        if n < fi.nparams or self.variadic(fi):
            ps.append("...")
        return ", ".join(ps)

    def function(self, fi, w):
        if getattr(fi, "template", None) is not None:
            return
        if fi.name == "main":
            w("main()\n{\n")
        else:
            kw = "public " if fi.public else "stock "
            tag = "Float:" if fi in self.float_ret else ""
            w("%s%s%s(%s)\n{\n" % (kw, tag, fi.name, self.params(fi)))
        body = list(fi.body)
        if body and body[-1].kind == "return" and isinstance(body[-1].e, Const) and body[-1].e.v == 0 \
                and not fi.ret_value and fi.addr not in self.used_value:
            body.pop()
        self.stmts(body, 1, w, fi)
        w("}\n\n")

    def write_natives(self, w):
        d = self.d
        # core declarations such as fopen(..., filemode:mode=io_readwrite) need their enum too
        for name in d.native_names:
            if self.core_ok(name):
                for en in ENUMS:
                    if en + ":" in CORE[name]["decl"]:
                        self.enums_used.add(en)
        if self.enums_used:
            w("// ---------------------------------------------------------- constants (as in file.inc/float.inc)\n")
            for en in ("filemode", "seek_whence", "floatround_method", "anglemode"):
                if en in self.enums_used:
                    w("enum %s { %s };\n" % (en, ", ".join(ENUMS[en])))
            w("\n")
        w("// ---------------------------------------------------------- natives\n")
        seen = set()
        for name in d.native_names:
            if name in seen:
                continue
            seen.add(name)
            if self.core_ok(name):
                w(CORE[name]["decl"] + "\n")
                continue
            if name in d.natdb:
                args, ret = d.natdb[name]
                cnts = d.arg_counts.get(name)
                if cnts and "m" not in args:
                    nmax = max(cnts)
                    args = (list(args) + ["i"] * nmax)[:nmax]
                elif cnts and max(cnts) <= args.index("m"):
                    # open.mp made many SA-MP natives variadic (SendClientMessage, ...);
                    # keep the classic declaration when the script never passes more
                    args = list(args[:args.index("m")])
                ps = []
                for i, t in enumerate(args):
                    if t == "m":
                        ps.append("{Float,_}:...")
                        break
                    pn = NATIVE_PNAMES.get(name)
                    on = d.nat_argnames.get(name, [])
                    if pn and len(pn) == len(args):
                        nm = pn[i]
                    elif i < len(on) and on[i] != "...":
                        nm = on[i]
                    else:
                        nm = {"p": "playerid", "v": "vehicleid", "o": "objectid"}.get(t, "p%d" % i)
                        if nm in ("playerid", "vehicleid", "objectid") and \
                                sum(1 for x in args if x == t) > 1:
                            nm = "%s%d" % (nm, i)
                    ps.append({"s": "const %s[]" % nm, "r": "&%s" % nm, "fr": "&Float:%s" % nm,
                               "f": "Float:%s" % nm}.get(t, nm))
                w("native %s%s(%s);\n" % ("Float:" if ret == "f" else "", name, ", ".join(ps)))
            else:
                modes = self.infer_native(name)
                ps = []
                for i, m in enumerate(modes):
                    if m == "va":
                        ps.append("{Float,_}:...")
                        break
                    ps.append({"a": "const p%d[]" % i, "r": "&p%d" % i}.get(m, "p%d" % i))
                w("native %s(%s); // signature inferred from calls\n" % (name, ", ".join(ps)))
        w("\n")

    def write_float_ops(self, w):
        u = self.ops_used
        if not u:
            return
        w("// ---------------------------------------------------------- float operators (as in float.inc)\n")
        for op, nat in (("*", "floatmul"), ("/", "floatdiv"), ("+", "floatadd"), ("-", "floatsub")):
            if op in u:
                w("native Float:operator%s(Float:oper1, Float:oper2) = %s;\n" % (op, nat))
        if "neg" in u:
            w("stock Float:operator-(Float:oper) return oper ^ Float:cellmin;\n")
        if "cmp" in u:
            for op in ("==", "!=", ">", ">=", "<", "<="):
                w("stock bool:operator%s(Float:oper1, Float:oper2) return floatcmp(oper1, oper2) %s 0;\n" % (op, op))
        w("\n")

    def write_globals(self, w):
        d, a, C = self.d, self.d.a, self.C
        w("// ---------------------------------------------------------- global variables\n")
        cells = a.data_cells
        pubv = {adr for adr, _ in a.pubvar_list}
        scal = sorted(x for x in d.g_scalar if 0 <= x < len(a.data) and self.owner(x) is None)
        allg = sorted(set(self.ginfo) | set(scal))
        for s0 in allg:
            pre = "new " if s0 not in pubv else "public "
            isf = ("g", s0) in self.F
            nm = ("Float:" if isf else "") + self.gname(s0)
            base = s0 // C
            if s0 not in self.ginfo:
                v = a.sval(cells[base]) if base < len(cells) else 0
                w("%s%s%s;\n" % (pre, nm, (" = %s" % self.r(Const(v), 2, "f" if isf or self.floatish(Const(v)) else "v")) if v else ""))
                continue
            inf = self.ginfo[s0]
            if inf[0] == "1d":
                size = inf[1]
                vals = [a.sval(x) for x in cells[base:base + size]]
                w("%s%s[%d]%s;\n" % (pre, nm, size, self.init1(vals, isf)))
            elif inf[0] == "2dr":
                rows, lens = inf[1], inf[2]
                db = base + rows
                out_rows = []
                for n in lens:
                    vals = [a.sval(x) for x in cells[db:db + n]]
                    db += n
                    k = 0
                    while k < n and vals[k] and (32 <= vals[k] < 256 or vals[k] in (9, 10, 13)):
                        k += 1
                    if k == n - 1 and vals[k] == 0:
                        out_rows.append(pawn_str("".join(chr(v) for v in vals[:k])))
                    else:
                        out_rows.append("{%s}" % ", ".join(self.r(Const(v)) for v in vals))
                w("%s%s[%d][] =\n{\n" % (pre, nm, rows))
                w(",\n".join("    " + r for r in out_rows))
                w("\n};\n")
            elif inf[0] == "3d":
                a3, b3, c3 = inf[1], inf[2], inf[3]
                db = base + a3 + a3 * b3
                vals = [a.sval(x) for x in cells[db:db + a3 * b3 * c3]]
                if any(vals):
                    blocks = []
                    for r in range(a3):
                        rows3 = []
                        for j in range(b3):
                            o = (r * b3 + j) * c3
                            rows3.append(self.init1(vals[o:o + c3], isf)[3:] or "{0}")
                        blocks.append("    {" + ", ".join(rows3) + "}")
                    w("%s%s[%d][%d][%d] =\n{\n" % (pre, nm, a3, b3, c3))
                    w(",\n".join(blocks))
                    w("\n};\n")
                else:
                    w("%s%s[%d][%d][%d];\n" % (pre, nm, a3, b3, c3))
            else:
                rows, cols = inf[1], inf[2]
                db = base + rows
                rowsv = [[a.sval(x) for x in cells[db + r * cols: db + (r + 1) * cols]] for r in range(rows)]
                if any(any(r) for r in rowsv):
                    w("%s%s[%d][%d] =\n{\n" % (pre, nm, rows, cols))
                    w(",\n".join("    " + (self.init1(r, isf)[3:] or "{0}") for r in rowsv))
                    w("\n};\n")
                else:
                    w("%s%s[%d][%d];\n" % (pre, nm, rows, cols))
        w("\n")

    def init1(self, vals, isf=False):
        if not any(vals):
            return ""
        if isf:
            vals = strip_zeros(vals)
            return " = {%s}" % ", ".join(self.r(Const(v), 0, "f") for v in vals)
        # string?
        k = 0
        while k < len(vals) and vals[k] and (32 <= vals[k] < 256 or vals[k] in (9, 10, 13)):
            k += 1
        if 0 < k < len(vals) and not any(vals[k:]):
            # (a string needs room for its terminating zero)
            return " = " + pawn_str("".join(chr(v) for v in vals[:k]))
        # a long run of one value up to the end: {..., x, x, ...} (Pawn repeats the last value)
        run = 1
        while run < len(vals) and vals[-run - 1] == vals[-1]:
            run += 1
        if vals[-1] != 0 and run >= 4:
            head = vals[:len(vals) - run]
            items = [self.r(Const(v)) for v in head] + [self.r(Const(vals[-1]))] * (1 if not head else 2)
            return " = {%s, ...}" % self.join_wrapped(items)
        vals = strip_zeros(vals)
        return " = {%s}" % self.join_wrapped([self.r(Const(v)) for v in vals])

    @staticmethod
    def join_wrapped(items, width=1000):
        """Join initializer items, breaking the line before pawncc's line length limit."""
        s = ", ".join(items)
        if len(s) <= width:
            return s
        lines, cur = [], []
        n = 0
        for it in items:
            if cur and n + len(it) > width:
                lines.append(", ".join(cur))
                cur, n = [], 0
            cur.append(it)
            n += len(it) + 2
        lines.append(", ".join(cur))
        return ",\n    ".join(lines)
