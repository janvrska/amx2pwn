"""Readability: library recognition, naming, sizeof/true/false and default arguments."""

from ..libraries import (
    FLOAT_BASIC, GENERIC_PNAMES, GLOBNAMES, LIBSIGS, OUTNAMES, PAWN_KEYWORDS, RETNAMES,
)
from ..literals import fmt_float_bits
from ..natives import CORE, ENUMS, NATIVE_PNAMES
from ..nodes import (
    AddrOf, Assign, Call, CharAt, Const, Elem, G, HeapTmp, iter_nodes, iter_stmts, L, PostInc,
    Prm, stmt_roots,
)


class ReadabilityMixin:
    """Readability: library recognition, naming, sizeof/true/false and default arguments."""

    def lib_features(self, fi):
        d = self.d
        f = dict(nat=set(), calls=[], strs=set(), consts=set(), ret_arr=False)
        for st in iter_stmts(fi.body):
            if st.kind == "return" and getattr(st, "arr", False):
                f["ret_arr"] = True
            for root in stmt_roots(st):
                for n in iter_nodes(root):
                    if isinstance(n, Call):
                        if n.native:
                            f["nat"].add(n.name)
                        elif n.faddr in d.fby and getattr(d.fby[n.faddr], "template", None) is None:
                            f["calls"].append(n.faddr)
                    elif isinstance(n, Const):
                        f["consts"].add(n.v)
                        t = d.strings.get(n.v)
                        if t is not None:
                            f["strs"].add(t.lstrip("\x01"))
        return f

    def lib_match(self, fi, f, cond):
        d = self.d
        if cond.get("np") is not None and fi.nparams != cond["np"]:
            return False
        if "ret_arr" in cond and f["ret_arr"] != cond["ret_arr"]:
            return False
        if not set(cond.get("nat", ())) <= f["nat"]:
            return False
        if "natonly" in cond and not (f["nat"] - FLOAT_BASIC) <= set(cond["natonly"]):
            return False
        if not all(any(x in t for t in f["strs"]) for x in cond.get("str", ())):
            return False
        if not set(cond.get("const", ())) <= f["consts"]:
            return False
        callees = {d.fby[a].name for a in f["calls"]}
        if not set(cond.get("calls", ())) <= callees:
            return False
        if cond.get("nocalls") and f["calls"]:
            return False
        if cond.get("nocreate") and "dini_Create" in callees:
            return False
        return True

    def rename_func(self, fi, nm):
        d = self.d
        old = fi.name
        fi.name = nm
        for c in self.all_calls:
            if not c.native and c.faddr == fi.addr:
                c.name = nm
        if old in d.arg_counts:
            d.arg_counts[nm] = d.arg_counts.pop(old)

    def identify_libs(self):
        """Name well-known library functions using LIBSIGS, and parameters after natives."""
        d = self.d
        used = {fi.name for fi in d.funcs} | set(d.native_names)
        cand = [fi for fi in d.funcs if fi.name.startswith("func_") and not fi.public
                and getattr(fi, "template", None) is None]
        feats = {id(fi): self.lib_features(fi) for fi in cand}
        changed = True
        while changed:
            changed = False
            for fi in cand:
                if not fi.name.startswith("func_"):
                    continue
                for nm, pnames, cond in LIBSIGS:
                    if self.lib_match(fi, feats[id(fi)], cond):
                        base, k = nm, 2
                        while nm in used:
                            nm = "%s%d" % (base, k)
                            k += 1
                        used.add(nm)
                        self.rename_func(fi, nm)
                        for i, pn in enumerate(pnames):
                            if i < fi.nparams:
                                fi.pnames[i] = pn
                        changed = True
                        break
        # script function parameters named after the native parameters they are passed to
        for fi in d.funcs:
            if fi.public and fi.name in d.cbdb:
                continue
            sugg = {}
            for st in iter_stmts(fi.body):
                for root in stmt_roots(st):
                    for n in iter_nodes(root):
                        if isinstance(n, Call) and n.native and n.name in NATIVE_PNAMES:
                            names = NATIVE_PNAMES[n.name]
                            if len(names) < len(n.args):
                                continue
                            for i, x in enumerate(n.args):
                                if isinstance(x, Prm) and x.f is fi:
                                    sugg.setdefault(x.k, set()).add(names[i])
            taken = set(fi.pnames.values())
            for k in sorted(sugg):
                ns = sugg[k]
                if k in fi.pnames or len(ns) != 1:
                    continue
                nm = ns.pop()
                if nm in GENERIC_PNAMES or nm in taken or nm in used or nm in PAWN_KEYWORDS:
                    continue
                fi.pnames[k] = nm
                taken.add(nm)

    def name_globals(self):
        d = self.d
        sugg = {}
        for fi in d.funcs:
            for st in iter_stmts(fi.body):
                for root in stmt_roots(st):
                    for n in iter_nodes(root):
                        if not (isinstance(n, Assign) and isinstance(n.v, Call) and n.v.native
                                and n.v.name in GLOBNAMES):
                            continue
                        t, own = n.t, None
                        if isinstance(t, G):
                            own = self.owner(t.addr)
                            own = t.addr if own is None else own
                        elif isinstance(t, Elem) and isinstance(t.ia.base, Const):
                            own = self.owner(t.ia.base.v)
                        if own is not None:
                            sugg.setdefault(own, set()).add(GLOBNAMES[n.v.name])
        self.gnames = {}
        for own, ns in sugg.items():
            if len(ns) == 1 and self.gname(own).startswith("g_"):
                self.gnames[own] = "%s_%X" % (ns.pop(), own)

    def loc_of(self, x):
        if isinstance(x, AddrOf):
            x = x.t
        if isinstance(x, L) and x.k in (None, 0):
            return x.loc
        return None

    def name_locals(self, fi, reserved):
        import re
        locs, forvars, sugg, nsugg, outer = {}, {}, {}, {}, {}

        def suggest(loc, nm):
            if loc is not None and nm and id(loc) not in sugg:
                sugg[id(loc)] = nm

        def visit(stmts, depth):
            for st in stmts:
                if st.kind == "decl":
                    locs[id(st.loc)] = st.loc
                    if isinstance(st.init, Call):
                        suggest(st.loc, RETNAMES.get(st.init.name))
                if st.kind == "for" and st.init is not None and st.init.kind == "decl":
                    locs[id(st.init.loc)] = st.init.loc
                    stepped = False
                    for x in iter_stmts(st.inc):
                        for root in stmt_roots(x):
                            for n in iter_nodes(root):
                                if isinstance(n, (PostInc, Assign)) and isinstance(n.t, L) \
                                        and n.t.loc is st.init.loc:
                                    stepped = True
                    if stepped:
                        forvars[id(st.init.loc)] = depth
                    elif isinstance(st.init.init, Call):
                        suggest(st.init.loc, RETNAMES.get(st.init.init.name))
                if st.kind == "for":
                    for x in iter_stmts(st.inc):
                        for root in stmt_roots(x):
                            for n in iter_nodes(root):
                                if isinstance(n, (PostInc, Assign)) and isinstance(n.t, L) and n.t.k is None \
                                        and n.t.loc.size == 1 and id(n.t.loc) not in forvars:
                                    outer.setdefault(id(n.t.loc), depth)
                roots = stmt_roots(st)
                if st.kind == "for" and st.init is not None:
                    roots += stmt_roots(st.init)
                for root in roots:
                    for n in iter_nodes(root):
                        if isinstance(n, L):
                            locs[id(n.loc)] = n.loc
                        if isinstance(n, Assign) and isinstance(n.v, Call):
                            suggest(self.loc_of(n.t) if n.arr else
                                    (n.t.loc if isinstance(n.t, L) and n.t.k is None else None),
                                    RETNAMES.get(n.v.name))
                        if isinstance(n, Call):
                            m = OUTNAMES.get(n.name)
                            if m:
                                for i, nm in m.items():
                                    lc = self.loc_of(n.args[i]) if i < len(n.args) else None
                                    if lc is not None and (lc.size > 1) == (nm in ("string", "name", "ip", "line", "value")):
                                        suggest(lc, nm)
                            if n.native and n.name in NATIVE_PNAMES:
                                names = NATIVE_PNAMES[n.name]
                                if len(names) >= len(n.args):
                                    for i, x in enumerate(n.args):
                                        if isinstance(x, L) and x.k is None:
                                            nsugg.setdefault(id(x.loc), set()).add(names[i])
                for sub in ("then", "els"):
                    v = getattr(st, sub, None)
                    if isinstance(v, list):
                        visit(v, depth)
                if st.kind in ("while", "do"):
                    visit(st.body, depth)
                if st.kind == "for":
                    visit(st.body, depth + 1)
                    visit(st.inc, depth + 1)
                if st.kind == "switch":
                    for _, _, b in st.cases:
                        visit(b, depth)

        visit(fi.body, 0)
        for k, ns in nsugg.items():
            if k not in sugg and k not in forvars and len(ns) == 1:
                nm = next(iter(ns))
                if nm not in GENERIC_PNAMES:
                    sugg[k] = nm
        used = set(reserved) | {self.pname(fi, k) for k in range(fi.nparams)}
        loopn = ["i", "j", "k", "m", "n"]
        used |= set(loopn)
        for k, loc in locs.items():
            if not re.match(r"var\d+$", loc.name):
                used.add(loc.name)
        for k, loc in locs.items():
            if k in forvars and forvars[k] < len(loopn) and re.match(r"var\d+$", loc.name):
                loc.name = loopn[forvars[k]]
        # counter declared before the loop: i/j/k only when the function has no 'new i' loops
        if not forvars:
            free = list(loopn)
            for k in sorted(outer, key=lambda k: outer[k]):
                loc = locs.get(k)
                if loc is not None and re.match(r"var\d+$", loc.name) and k not in sugg and free:
                    loc.name = free.pop(0)
                    forvars[k] = 0
        for k, loc in sorted(locs.items(), key=lambda kv: int(kv[1].name[3:]) if re.match(r"var\d+$", kv[1].name) else -1):
            if k in forvars or k not in sugg or not re.match(r"var\d+$", loc.name):
                continue
            base = nm = sugg[k]
            n = 2
            while nm in used:
                nm = "%s%d" % (base, n)
                n += 1
            used.add(nm)
            loc.name = nm

    def find_strarrs(self):
        """Arrays that are passed as strings (for 'a' and EOS)."""
        d = self.d
        out = set()
        for c in self.all_calls:
            if not c.native or c.name not in d.natdb:
                continue
            letters = d.natdb[c.name][0]
            for i, x in enumerate(c.args):
                if i < len(letters) and letters[i] == "s":
                    k = self.str_key(x)
                    if k is not None:
                        out.add(k)
        self.strarrs = out

    def str_key(self, x):
        if isinstance(x, AddrOf):
            x = x.t
        if isinstance(x, L):
            return ("l", id(x.loc))
        if isinstance(x, Prm):
            return ("p", id(x.f), x.k)
        if isinstance(x, Const) and self.layout_ready:
            own = self.owner(x.v)
            return ("g", own) if own is not None else None
        return None

    def is_char(self, e):
        if isinstance(e, CharAt):
            return True
        if isinstance(e, Elem):
            b = e.ia.base
            return self.str_key(b) in getattr(self, "strarrs", ())
        if isinstance(e, L) and e.k is not None and e.loc.size > 1:
            return ("l", id(e.loc)) in getattr(self, "strarrs", ())
        return False

    def arr_size(self, x):
        if isinstance(x, AddrOf) and isinstance(x.t, L) and x.t.k in (None, 0) and x.t.loc.size > 1 \
                and x.t.loc.dims is None:
            return x.t.loc.size
        if isinstance(x, Const) and self.layout_ready and self.owner(x.v) == x.v:
            inf = self.ginfo.get(x.v)
            if inf and inf[0] == "1d" and inf[1] > 1:
                return inf[1]
        return None

    def core_ok(self, name):
        info = CORE.get(name)
        if info is None:
            return None
        cnts = self.d.arg_counts.get(name) or set()
        for c in cnts:
            if c < info["nreq"] or (c > info["n"] and not info["va"]):
                return None
        return info

    def nice_args(self, c, args):
        """sizeof(array), true/false, enum constants and dropping default arguments."""
        import re
        for i in range(1, len(c.args)):
            x = c.args[i]
            if isinstance(x, Const) and x.v > 1 and self.arr_size(c.args[i - 1]) == x.v \
                    and re.match(r"\w+$", args[i - 1]):
                args[i] = "sizeof(%s)" % args[i - 1]
        info = self.core_ok(c.name) if c.native else None
        if not info:
            return args
        defs = info["defs"]

        def is_default(i):
            dd = defs[i] if i < len(defs) else None
            x = c.args[i]
            if isinstance(x, HeapTmp) and isinstance(x.content, Const):
                x = x.content       # default value of a reference argument (&second=0) lives on the heap
            if dd is None or not isinstance(x, Const):
                return False
            if dd[0] == "sz":
                return self.arr_size(c.args[dd[1]]) == x.v
            return x.v == dd[-1]

        while args and len(args) - 1 < len(defs) and is_default(len(args) - 1):
            args.pop()
        for i in range(len(args)):
            dd = defs[i] if i < len(defs) else None
            x = c.args[i]
            if dd is None or not isinstance(x, Const):
                continue
            if dd[0] == "bool" and x.v in (0, 1):
                args[i] = "true" if x.v else "false"
            elif dd[0] == "enum":
                members = ENUMS[dd[1]]
                if 0 <= x.v < len(members):
                    args[i] = members[x.v]
        for i, tag in enumerate(info["kinds"]):
            if tag in ENUMS:
                self.enums_used.add(tag)
                if i < len(args) and not isinstance(c.args[i], Const):
                    args[i] = "%s:%s" % (tag, args[i])
        return args

    def fa(self, x, prec):
        """Operand of a float operator (must carry the Float tag)."""
        if isinstance(x, Const):
            fs = fmt_float_bits(x.v)
            if fs is None:
                return "Float:%d" % x.v if x.v >= 0 else "Float:(%d)" % x.v
            return fs if not fs.startswith("-") or prec <= 13 else "(%s)" % fs
        if isinstance(x, Call) and x.native and x.name == "float" and len(x.args) == 1 \
                and isinstance(x.args[0], Const) and abs(x.args[0].v) < 10000000:
            v = x.args[0].v
            return ("%d.0" % v) if v >= 0 or prec <= 13 else "(%d.0)" % v
        if self.ftag(x):
            return self.r(x, prec)
        return "Float:" + self.r(x, 15)

    def ia_cast(self, x, prec, cast):
        return ("_:" + self.r(x, 15)) if cast else self.r(x, prec)
