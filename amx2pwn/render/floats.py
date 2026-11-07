"""Float: tag inference and float operator templates."""

from ..nodes import (
    AddrOf, Assign, Bin, Call, CharAt, CMP_OPS, Const, Elem, FLOAT_NATIVES, FOPS, G, HeapTmp,
    IA, L, N, PostInc, Prm, Raw, Row, subst, Tern, Un,
)


class FloatsMixin:
    """Float: tag inference and float operator templates."""

    def gkey(self, addr):
        own = self.owner(addr) if self.layout_ready else None
        return ("g", own if own is not None else addr)

    def fkey(self, e):
        """Variable key for the Float tag. An element with a constant index gets its own key ("e", array, index)."""
        if isinstance(e, L):
            self.locs[id(e.loc)] = e.loc
            if e.k is not None and e.loc.size > 1:
                return ("e", ("l", id(e.loc)), e.k)
            return ("l", id(e.loc))
        if isinstance(e, G):
            own = self.owner(e.addr) if self.layout_ready else None
            if own is not None and (own != e.addr or self.gsize(own) > 1):
                k = (e.addr - own) // self.C
                inf = self.ginfo[own]
                if inf[0] == "2d" and k >= inf[1]:
                    k = (k - inf[1]) % inf[2]
                elif inf[0] == "2dr" and k >= inf[1]:
                    k = self.ragged_pos(inf, k)[1]
                elif inf[0] == "3d" and k >= inf[1] + inf[1] * inf[2]:
                    k = (k - inf[1] - inf[1] * inf[2]) % inf[3]
                return ("e", ("g", own), k)
            return self.gkey(e.addr)
        if isinstance(e, Prm):
            return ("p", id(e.f), e.k)
        if isinstance(e, AddrOf):
            return self.fkey(e.t)
        if isinstance(e, (Elem, IA)):
            ia = e.ia if isinstance(e, Elem) else e
            b = ia.base
            bk = self.gkey(b.v) if isinstance(b, Const) else self.fkey(b)
            if bk is not None and isinstance(ia.idx, Const):
                return ("e", bk, ia.idx.v)
            return bk
        if isinstance(e, Row):
            return self.fkey(e.x)
        if isinstance(e, HeapTmp) and e.content is not None:
            return self.fkey(e.content)
        return None

    def template_of(self, c):
        if c.native or c.faddr not in self.d.fby:
            return None
        return getattr(self.d.fby[c.faddr], "template", None)

    def expand(self, c):
        fi = self.d.fby[c.faddr]
        t = fi.template
        if t == "neg":
            return Un("fneg", c.args[0] if c.args else Const(0))
        return subst(t, c.args, fi)

    def ftag(self, e):
        if isinstance(e, (L, G, Prm, Elem)):
            k = self.fkey(e)
            if k is None:
                return False
            if k[0] == "e":
                return k[1] in self.F
            return k in self.F
        if isinstance(e, Call):
            if e.native:
                if e.name in FOPS or e.name == "float":
                    return True
                return e.name in self.d.natdb and self.d.natdb[e.name][1] == "f"
            if self.template_of(e) is not None:
                return self.ftag(self.expand(e))
            return e.faddr in self.d.fby and self.d.fby[e.faddr] in self.float_ret
        if isinstance(e, Tern):
            return self.ftag(e.a) and self.ftag(e.b)
        if isinstance(e, (Assign, PostInc)):
            return self.ftag(e.t)
        if isinstance(e, HeapTmp):
            return e.content is not None and self.ftag(e.content)
        if isinstance(e, Un) and e.op == "fneg":
            return True
        return False

    def letters(self, c):
        d = self.d
        if c.name not in d.natdb:
            return []
        letters = d.natdb[c.name][0]
        cnts = d.arg_counts.get(c.name)
        if cnts and "m" not in letters:
            letters = (list(letters) + ["i"] * max(cnts))[:max(cnts)]
        return letters

    def detect_float_ops(self):
        """Operators from float.inc compiled into the script -> templates."""
        for fi in self.d.funcs:
            body = [x for x in fi.body]
            if fi.public or len(body) != 1 or body[0].kind != "return" or body[0].e is None:
                continue
            e = body[0].e
            if isinstance(e, Bin) and e.op == "^" and isinstance(e.a, Prm) and isinstance(e.b, Const) \
                    and (e.b.v & 0xFFFFFFFF) == 0x80000000:
                fi.template = "neg"
                continue
            seen = []
            ok = [True]
            nat = [False]

            def chk(x):
                if isinstance(x, Prm) and x.f is fi:
                    seen.append(x.k)
                elif isinstance(x, Const):
                    pass
                elif isinstance(x, Call) and x.native and x.name in FLOAT_NATIVES:
                    nat[0] = True
                    for y in x.args:
                        chk(y)
                elif isinstance(x, Bin) and x.op in CMP_OPS:
                    chk(x.a)
                    chk(x.b)
                else:
                    ok[0] = False
            chk(e)
            if ok[0] and nat[0] and sorted(seen) == list(range(len(seen))) and len(seen) == fi.nparams:
                fi.template = e

    def infer_floats(self):
        d = self.d
        F = self.F
        self.changed = True

        def mark(x):
            if x is None or isinstance(x, (Const, Raw)):
                return
            k = self.fkey(x)
            if k is not None and k not in F:
                F.add(k)
                self.changed = True

        def walk(e, fi):
            if e is None or not isinstance(e, N):
                return
            if isinstance(e, Call):
                tpl = self.template_of(e)
                if tpl is not None:
                    walk(self.expand(e), fi)
                    return
                if e.native:
                    lt = self.letters(e)
                    for i, x in enumerate(e.args):
                        t = lt[i] if i < len(lt) else None
                        if t in ("f", "fr"):
                            mark(x)
                elif e.faddr in d.fby:
                    callee = d.fby[e.faddr]
                    for i, x in enumerate(e.args):
                        pk = ("p", id(callee), i)
                        if self.ftag(x) and pk not in F:
                            F.add(pk)
                            self.changed = True
            elif isinstance(e, Un) and e.op == "fneg":
                mark(e.a)
            elif isinstance(e, Assign) and not e.arr:
                if self.ftag(e.v):
                    mark(e.t)
            for k in e.kids():
                walk(k, fi)

        def walk_stmts(stmts, fi):
            for st in stmts:
                for attr in ("e", "c"):
                    v = getattr(st, attr, None)
                    if isinstance(v, N):
                        walk(v, fi)
                if st.kind == "decl" and isinstance(st.init, N) and not st.arr:
                    walk(st.init, fi)
                    if self.ftag(st.init):
                        k = ("l", id(st.loc))
                        if k not in F:
                            F.add(k)
                            self.changed = True
                if st.kind == "return" and isinstance(st.e, N) and not getattr(st, "arr", False):
                    if self.ftag(st.e) and fi not in self.float_ret:
                        self.float_ret.add(fi)
                        self.changed = True
                for sub in ("then", "els", "body", "inc"):
                    v = getattr(st, sub, None)
                    if isinstance(v, list):
                        walk_stmts(v, fi)
                if st.kind == "for" and st.init is not None:
                    walk_stmts([st.init], fi)
                if st.kind == "switch":
                    for _, _, b in st.cases:
                        walk_stmts(b, fi)

        for _ in range(12):
            if not self.changed:
                break
            self.changed = False
            for fi in d.funcs:
                if getattr(fi, "template", None) is None:
                    walk_stmts(fi.body, fi)
            groups = {}
            for k in F:
                if k[0] == "e":
                    groups.setdefault(k[1], set()).add(k[2])
            for base, idxs in groups.items():
                if base in F:
                    continue
                n = self.arr_width(base)
                if n and len(idxs) >= n:
                    F.add(base)
                    self.changed = True

    def arr_width(self, base):
        if base[0] == "g":
            inf = self.ginfo.get(base[1])
            if not inf:
                return 0
            if inf[0] == "2dr":
                return max(inf[2])
            return inf[1] if inf[0] == "1d" else inf[3] if inf[0] == "3d" else inf[2]
        if base[0] == "l":
            loc = self.locs.get(base[1])
            return loc.size if loc is not None else 0
        return 0

    def infer_const(self):
        """An array parameter is const when the function neither writes to it nor passes it on for writing."""
        d = self.d
        nonconst = set()

        def base_prm(t):
            while True:
                if isinstance(t, Elem):
                    t = t.ia.base
                elif isinstance(t, (IA, CharAt)):
                    t = t.base
                elif isinstance(t, Row):
                    t = t.x
                elif isinstance(t, Bin) and t.op == "+":
                    t = t.a
                elif isinstance(t, AddrOf):
                    t = t.t
                else:
                    return t if isinstance(t, Prm) else None

        passes = []

        def walk(e):
            if e is None or not isinstance(e, N):
                return
            if isinstance(e, Assign):
                pm = base_prm(e.t)
                if pm is not None:
                    nonconst.add((id(pm.f), pm.k))
            if isinstance(e, PostInc):
                pm = base_prm(e.t)
                if pm is not None:
                    nonconst.add((id(pm.f), pm.k))
            if isinstance(e, Call) and not e.native and e.faddr in d.fby:
                for i, x in enumerate(e.args):
                    pm = base_prm(x)
                    if pm is not None:
                        passes.append(((id(pm.f), pm.k), (id(d.fby[e.faddr]), i)))
            for k in e.kids():
                walk(k)

        def walk_stmts(stmts):
            for st in stmts:
                for attr in ("e", "c", "init"):
                    v = getattr(st, attr, None)
                    if isinstance(v, N):
                        walk(v)
                for sub in ("then", "els", "body", "inc"):
                    v = getattr(st, sub, None)
                    if isinstance(v, list):
                        walk_stmts(v)
                if st.kind == "for" and st.init is not None:
                    walk_stmts([st.init])
                if st.kind == "switch":
                    for _, _, b in st.cases:
                        walk_stmts(b)

        for fi in d.funcs:
            walk_stmts(fi.body)
        changed = True
        while changed:
            changed = False
            for src, dst in passes:
                if dst in nonconst and src not in nonconst:
                    nonconst.add(src)
                    changed = True
        self.nonconst = nonconst
