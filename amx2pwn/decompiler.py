"""Decompiler: simulates AMX bytecode and rebuilds structured Pawn statements."""

import bisect

from .natives import load_samp_db
from .nodes import (
    AddrOf, as_cond, as_val, Assign, Bin, Call, CharAt, clear_key_cache, cond_tern, Const,
    const_truth, Deref, Elem, FALSE, FuncInfo, G, HeapTmp, IA, is_bool, Item, iter_nodes, L,
    Local, neg, Path, PostInc, Prm, Raw, Row, S, same, ScanFail, State, Tern, TRUE, Un,
    val_tern,
)


class Decompiler:
    JCOND = {"jzer", "jnz", "jeq", "jneq", "jless", "jleq", "jgrtr", "jgeq",
             "jsless", "jsleq", "jsgrtr", "jsgeq"}
    JOP = {"jeq": "==", "jneq": "!=", "jless": "<", "jleq": "<=", "jgrtr": ">", "jgeq": ">=",
           "jsless": "<", "jsleq": "<=", "jsgrtr": ">", "jsgeq": ">="}
    CMP = {"eq": "==", "neq": "!=", "less": "<", "leq": "<=", "grtr": ">", "geq": ">=",
           "sless": "<", "sleq": "<=", "sgrtr": ">", "sgeq": ">="}

    def __init__(self, amx):
        self.a = amx
        self.C = amx.cell
        self.ins = amx.disassemble()
        self.addrs = [x[0] for x in self.ins]
        self.idx_of = {a: k for k, a in enumerate(self.addrs)}
        self.strings = amx.find_strings()
        self.natdb, self.cbdb, self.nat_argnames = load_samp_db()
        self.native_names = amx.native_list
        # jump targets
        self.labels = set()
        self.back_src = {}
        for k, (addr, n, ops) in enumerate(self.ins):
            if n in self.JCOND or n == "jump":
                t = ops[0]
                self.labels.add(t)
                if t <= addr:
                    self.back_src.setdefault(t, []).append(k)
            elif n == "switch":
                self.labels.add(ops[0])
            elif n == "casetbl":
                self.labels.add(ops[1])
                for t in range(ops[0]):
                    self.labels.add(ops[3 + 2 * t])
        # global variables
        self.g_scalar = set()
        self.g_arr = {}       # addr -> size from bounds (0 = unknown)
        self.layout = None
        self.arg_counts = {}  # native/function -> set(argument counts)
        self.nat_modes = {}   # native -> {position: 'a'|'r'|'va'}
        # functions
        self.funcs = []
        self.fby = {}
        pubs = {a: n for a, n in amx.public_list}
        starts = [k for k, x in enumerate(self.ins) if x[1] == "proc"]
        for j, k in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else len(self.ins)
            addr = self.ins[k][0]
            if addr in pubs:
                name = pubs[addr]
            elif addr == amx.cip:
                name = "main"
            else:
                name = "func_%X" % addr
            for s in amx.dbg_symbols:
                if s["ident"] == 9 and s["addr"] == addr:
                    name = s["name"]
            fi = FuncInfo(addr, name, addr in pubs)
            fi.k0, fi.k1 = k, end
            if fi.public and name in self.cbdb:
                for i, p in enumerate(self.cbdb[name]):
                    if p.endswith("[]"):
                        fi.pkind[i] = "a"
                        p = p[:-2]
                    fi.pnames[i] = p.split(":")[-1]
                fi.nparams = len(self.cbdb[name])
            self.funcs.append(fi)
            self.fby[addr] = fi

    # ------------------------------------------------------------------
    def idx(self, addr):
        k = self.idx_of.get(addr)
        if k is not None:
            return k
        return bisect.bisect_left(self.addrs, addr)

    def addr_at(self, k):
        return self.addrs[k] if k < len(self.addrs) else (self.addrs[-1] + self.C if self.addrs else 0)

    # ---------------- side effects / emitting ----------------
    def use(self, st, e):
        if not st.fx or e is None:
            return
        todo = [e]
        while todo:
            x = todo.pop()
            for k, f in enumerate(st.fx):
                if f is x:
                    del st.fx[k]
                    break
            todo.extend(c for c in x.kids() if c is not None)

    def emit(self, st, out, stmt, exprs=()):
        if self.tentative:
            raise ScanFail()
        for e in exprs:
            self.use(st, e)
        self.declare_pending(st, out)
        self.flush_fx(st, out)
        out.append(stmt)

    def flush_fx(self, st, out):
        if st.fx:
            if self.tentative:
                raise ScanFail()
            for e in st.fx:
                out.extend(self.effect_stmts(e))
            st.fx = []

    @staticmethod
    def has_effect(e):
        return any(isinstance(x, (Call, Assign, PostInc)) for x in iter_nodes(e))

    def effect_stmts(self, e):
        """Statements for an unused expression; 'c ? f() : x' becomes 'if (c) f();'."""
        if not isinstance(e, Tern):
            return [S("expr", e=e)]
        then = self.effect_stmts(e.a) if self.has_effect(e.a) else []
        els = self.effect_stmts(e.b) if self.has_effect(e.b) else []
        if not then and not els:
            return []
        if not then:
            return [S("if", c=neg(e.c), then=els, els=None)]
        return [S("if", c=e.c, then=then, els=els or None)]

    def pure_addr(self, e, st, offs, gaddrs, under_row):
        """Element address that is safe to compute again: only variables and 2D array headers."""
        if isinstance(e, Const):
            return True
        if isinstance(e, Prm):
            offs.add((3 + e.k) * self.C)
            return True
        if isinstance(e, L):
            if e.k is not None and e.loc.size > 1:
                return False
            for x in st.stk:
                if x.local is e.loc:
                    offs.add(x.off)
                    return True
            return False
        if isinstance(e, G):
            gaddrs.add(e.addr)
            return True
        if isinstance(e, AddrOf):
            return isinstance(e.t, L) and e.t.loc.size > 1
        if isinstance(e, IA):
            return self.pure_addr(e.base, st, offs, gaddrs, False) and \
                    self.pure_addr(e.idx, st, offs, gaddrs, False)
        if isinstance(e, Row):
            return self.pure_addr(e.x, st, offs, gaddrs, True)
        if isinstance(e, Elem):
            return under_row and self.pure_addr(e.ia, st, offs, gaddrs, False)
        if isinstance(e, Bin) and e.op in ("+", "-", "*"):
            return self.pure_addr(e.a, st, offs, gaddrs, False) and \
                    self.pure_addr(e.b, st, offs, gaddrs, False)
        return False

    def declare_pending(self, st, out):
        self.cur_st = st
        for k in range(st.frozen, len(st.stk)):
            it = st.stk[k]
            if it.local is None and not self.stable(it):
                self.declare(st, it, out, it.expr)

    def stable(self, it):
        """Array address pushed before s[++i]: it does not change and nothing refers to its
        stack slot, so it does not need to be stored in a temporary variable."""
        e = it.expr
        st = self.cur_st
        if it not in st.stk:
            return False
        offs, gaddrs = set(), set()
        if isinstance(e, AddrOf) and isinstance(e.t, L) and e.t.loc.size > 1:
            ok = True
        elif isinstance(e, Prm):
            ok = (3 + e.k) * self.C not in self.cur_written
        elif isinstance(e, (IA, Row)):
            ok = self.pure_addr(e, st, offs, gaddrs, False)
        else:
            return False
        if not ok:
            return False
        fi = self.cur
        d = sum(x.size for x in st.stk[st.stk.index(it) + 1:])
        last = None
        for x in self.ins[getattr(self, "cur_k", fi.k0):fi.k1]:
            op, args = x[1], x[2]
            if op == "break" or op.startswith(("ret", "jump", "j", "swap", "switch", "casetbl")):
                return False
            if (op.endswith(".s") or ".s." in op or op in ("addr.pri", "addr.alt")) and args and args[0] == it.off:
                return False
            if op in ("stor.s.pri", "stor.s.alt", "inc.s", "dec.s", "zero.s") and args and args[0] in offs:
                return False
            if op in ("stor.pri", "stor.alt", "inc", "dec", "zero") and args and args[0] in gaddrs:
                return False
            if op.startswith("push"):
                n = int(op[4]) if len(op) > 4 and op[4].isdigit() else 1
                d += n
                if op == "push.c":
                    last = args[0]
            elif op in ("pop.pri", "pop.alt"):
                if d == 0:
                    return True
                d -= 1
            elif op == "stack":
                d -= args[0] // self.C
                if d < 0:
                    return True
            elif op == "call":
                if last is None:
                    return False
                d -= last // self.C + 1
                if d < 0:
                    return True
        return False

    def declare(self, st, it, out, init):
        if self.tentative:
            raise ScanFail()
        fi = self.cur
        loc = Local("var%d" % fi.nloc, it.size)
        fi.nloc += 1
        it.local = loc
        if isinstance(init, Const) and init.v == 0 and it.size == 1:
            init = None
        out.append(S("decl", loc=loc, init=init, arr=False))
        return loc

    # ---------------- stack ----------------
    def push(self, st, e):
        self.use(st, e)
        st.sp -= self.C
        st.stk.append(Item(st.sp, e))

    def pop(self, st):
        st.sp += self.C
        if not st.stk:
            return Raw("/*pop*/0")
        it = st.stk.pop()
        if len(st.stk) < st.frozen:
            st.frozen = len(st.stk)
        if it.local is not None:
            return L(it.local, None if it.local.size == 1 else 0)
        return it.expr if it.expr is not None else Raw("/*?*/0")

    def frame(self, st, out, off):
        C = self.C
        if off >= 3 * C:
            k = (off - 3 * C) // C
            fi = self.cur
            fi.nparams = max(fi.nparams, k + 1)
            fi.used_params.add(k)
            return Prm(fi, k)
        for it in reversed(st.stk):
            if it.off <= off < it.off + it.size * C:
                if it.local is None:
                    self.declare(st, it, out, it.expr)
                k = (off - it.off) // C
                return L(it.local, None if it.local.size == 1 else k)
        return Raw("frm_%d" % (-off))

    def store_frame(self, st, out, off, v):
        for it in reversed(st.stk):
            if it.off <= off < it.off + it.size * self.C:
                if it.local is None and it.size == 1 and not self.tentative:
                    self.use(st, v)
                    self.declare_pending_except(st, out, it)
                    self.flush_fx(st, out)
                    self.declare(st, it, out, v)
                    return
                break
        self.assign(st, out, self.frame(st, out, off), v)

    def declare_pending_except(self, st, out, skip):
        for k in range(st.frozen, len(st.stk)):
            it = st.stk[k]
            if it.local is None and it is not skip:
                self.declare(st, it, out, it.expr)

    def assign(self, st, out, t, v, arr=False):
        if self.tentative and getattr(self, "exploring", False) and v is st.pri and not arr:
            # assignment inside a condition: if ((x = f()) != 0)
            self.use(st, v)
            st.pri = Assign(t, v)
            return
        self.emit(st, out, S("expr", e=Assign(t, v, arr)), [v, t])
        if st.pri is v and isinstance(v, (Call, PostInc, Tern)):
            st.pri = t

    # ---------------- addresses -> values ----------------
    def deref(self, e):
        if isinstance(e, IA):
            return Elem(e)
        if isinstance(e, Bin) and e.op in ("+", "-") and isinstance(e.b, Const) and e.b.v % self.C == 0 \
                and isinstance(e.a, (Prm, AddrOf, Row)):
            self.mark_base(e.a)
            k = e.b.v // self.C
            return Elem(IA(e.a, Const(k if e.op == "+" else -k)))
        if isinstance(e, AddrOf):
            return e.t
        if isinstance(e, Const):
            self.g_scalar.add(e.v)
            return G(e.v)
        if isinstance(e, HeapTmp):
            return e.content if e.content is not None else Raw("0")
        if isinstance(e, Prm):
            self.cur.pkind.setdefault(e.k, "a")
            return Elem(IA(e, Const(0)))
        if isinstance(e, Row):
            return Elem(IA(e, Const(0)))
        return Deref(e)

    def mark_base(self, b):
        if isinstance(b, Const) and b.v % self.C == 0 and 0 <= b.v < len(self.a.data):
            self.g_arr.setdefault(b.v, 0)
        elif isinstance(b, Prm):
            if self.cur.pkind.get(b.k) != "r":
                self.cur.pkind[b.k] = "a"

    def same_loc(self, x, y):
        if isinstance(x, G) and isinstance(y, (G, Const)):
            return x.addr == (y.addr if isinstance(y, G) else y.v)
        if isinstance(x, L) and isinstance(y, L):
            return x.loc is y.loc and x.k == y.k
        return False

    # ---------------- simulating one instruction ----------------
    def sim(self, k, st, out):
        self.cur_k = k
        addr, n, ops = self.ins[k]
        C = self.C
        o = ops[0] if ops else None
        if n in ("break", "nop", "line", "file", "symbol", "srange", "symtag", "bounds",
                 "align.pri", "align.alt", "sign.pri", "sign.alt", "proc"):
            if n == "bounds":
                self.last_bounds = o
            return
        if n == "load.pri":
            self.g_scalar.add(o); st.pri = G(o)
        elif n == "load.alt":
            self.g_scalar.add(o); st.alt = G(o)
        elif n == "load.s.pri":
            st.pri = self.frame(st, out, o)
        elif n == "load.s.alt":
            st.alt = self.frame(st, out, o)
        elif n in ("lref.s.pri", "lref.s.alt"):
            p = self.frame(st, out, o)
            if isinstance(p, Prm):
                self.cur.pkind[p.k] = "r"
            if n.endswith("pri"):
                st.pri = p
            else:
                st.alt = p
        elif n in ("lref.pri", "lref.alt"):
            self.g_scalar.add(o)
            v = Deref(G(o))
            if n.endswith("pri"):
                st.pri = v
            else:
                st.alt = v
        elif n == "load.i":
            st.pri = self.deref(st.pri)
        elif n == "lodb.i":
            st.pri = self.char_at(st.pri)
        elif n == "const.pri":
            st.pri = Const(o)
        elif n == "const.alt":
            st.alt = Const(o)
        elif n == "addr.pri":
            st.pri = AddrOf(self.frame(st, out, o))
        elif n == "addr.alt":
            st.alt = AddrOf(self.frame(st, out, o))
        elif n == "stor.pri":
            self.g_scalar.add(o); self.assign(st, out, G(o), st.pri)
        elif n == "stor.alt":
            self.g_scalar.add(o); self.assign(st, out, G(o), st.alt)
        elif n == "stor.s.pri":
            self.store_frame(st, out, o, st.pri)
        elif n == "stor.s.alt":
            self.store_frame(st, out, o, st.alt)
        elif n in ("sref.s.pri", "sref.s.alt"):
            p = self.frame(st, out, o)
            if isinstance(p, Prm):
                self.cur.pkind[p.k] = "r"
            self.assign(st, out, p, st.pri if n.endswith("pri") else st.alt)
        elif n in ("sref.pri", "sref.alt"):
            self.g_scalar.add(o)
            self.assign(st, out, Deref(G(o)), st.pri if n.endswith("pri") else st.alt)
        elif n == "stor.i":
            if isinstance(st.alt, HeapTmp):
                self.use(st, st.pri)
                st.alt.content = st.pri
            else:
                self.assign(st, out, self.deref(st.alt), st.pri)
        elif n == "strb.i":
            self.assign(st, out, self.char_at(st.alt), st.pri)
        elif n in ("lidx", "lidx.b"):
            self.mark_base(st.alt)
            self.note_bounds(st.alt)
            st.pri = Elem(IA(st.alt, st.pri))
        elif n in ("idxaddr", "idxaddr.b"):
            self.mark_base(st.alt)
            self.note_bounds(st.alt)
            st.pri = IA(st.alt, st.pri)
        elif n == "move.pri":
            st.pri = st.alt
        elif n == "move.alt":
            st.alt = st.pri
        elif n == "xchg":
            st.pri, st.alt = st.alt, st.pri
        elif n == "swap.pri" or n == "swap.alt":
            if st.stk:
                it = st.stk[-1]
                old = it.expr if it.local is None else L(it.local)
                if n == "swap.pri":
                    it.expr, st.pri = st.pri, old
                else:
                    it.expr, st.alt = st.alt, old
        elif n == "push.pri":
            self.push(st, st.pri)
        elif n == "push.alt":
            self.push(st, st.alt)
        elif n == "push.c":
            self.push(st, Const(o))
        elif n == "push":
            self.g_scalar.add(o); self.push(st, G(o))
        elif n == "push.s":
            self.push(st, self.frame(st, out, o))
        elif n == "push.adr":
            self.push(st, AddrOf(self.frame(st, out, o)))
        elif n == "push.r":
            for _ in range(max(0, o)):
                self.push(st, Const(0))
        elif n[:5] in ("push2", "push3", "push4", "push5"):
            kind = n[5:]
            for x in ops:
                if kind == ".c":
                    self.push(st, Const(x))
                elif kind == ".s":
                    self.push(st, self.frame(st, out, x))
                elif kind == ".adr":
                    self.push(st, AddrOf(self.frame(st, out, x)))
                else:
                    self.g_scalar.add(x); self.push(st, G(x))
        elif n == "pop.pri":
            st.pri = self.pop(st)
        elif n == "pop.alt":
            st.alt = self.pop(st)
        elif n == "stack":
            st.sp += o
            if o < 0:
                st.stk.append(Item(st.sp, None, -o // C))
            else:
                while st.stk and st.stk[-1].off < st.sp:
                    st.stk.pop()
                st.frozen = min(st.frozen, len(st.stk))
        elif n == "heap":
            if o > 0:
                st.alt = HeapTmp()
        elif n == "call":
            self.do_call(st, out, o, False)
        elif n == "sysreq.c":
            self.do_call(st, out, o, True)
        elif n in ("sysreq.n", "sysreq.nd"):
            self.do_call(st, out, o, True, ops[1])
        elif n in ("shl", "shr", "sshr"):
            st.pri = Bin({"shl": "<<", "shr": ">>>", "sshr": ">>"}[n], st.pri, st.alt)
        elif n in ("shl.c.pri", "shr.c.pri"):
            st.pri = Bin("<<" if n.startswith("shl") else ">>>", st.pri, Const(o))
        elif n in ("shl.c.alt", "shr.c.alt"):
            st.alt = Bin("<<" if n.startswith("shl") else ">>>", st.alt, Const(o))
        elif n in ("smul", "umul"):
            st.pri = Bin("*", st.pri, st.alt)
        elif n in ("sdiv", "udiv"):
            p, a = st.pri, st.alt
            st.pri, st.alt = Bin("/", p, a), Bin("%", p, a)
        elif n in ("sdiv.alt", "udiv.alt"):
            p, a = st.pri, st.alt
            st.pri, st.alt = Bin("/", a, p), Bin("%", a, p)
        elif n == "add":
            st.pri = self.add(st.pri, st.alt)
        elif n == "sub":
            st.pri = Bin("-", st.pri, st.alt)
        elif n == "sub.alt":
            st.pri = Bin("-", st.alt, st.pri)
        elif n in ("and", "or", "xor"):
            st.pri = Bin({"and": "&", "or": "|", "xor": "^"}[n], st.pri, st.alt)
        elif n == "not":
            st.pri = neg(st.pri) if is_bool(st.pri) else Un("!", st.pri)
        elif n == "neg":
            st.pri = Un("-", st.pri)
        elif n == "invert":
            st.pri = Un("~", st.pri)
        elif n == "add.c":
            st.pri = self.add(st.pri, Const(o))
        elif n == "smul.c":
            st.pri = Bin("*", st.pri, Const(o))
        elif n == "zero.pri":
            st.pri = Const(0)
        elif n == "zero.alt":
            st.alt = Const(0)
        elif n == "zero":
            self.g_scalar.add(o); self.assign(st, out, G(o), Const(0))
        elif n == "zero.s":
            self.store_frame(st, out, o, Const(0))
        elif n in self.CMP:
            st.pri = Bin(self.CMP[n], st.pri, st.alt)
        elif n == "eq.c.pri":
            st.pri = Bin("==", st.pri, Const(o))
        elif n == "eq.c.alt":
            st.pri = Bin("==", st.alt, Const(o))
        elif n in ("inc.pri", "dec.pri"):
            st.pri = Bin("+" if n[0] == "i" else "-", st.pri, Const(1))
        elif n in ("inc.alt", "dec.alt"):
            st.alt = Bin("+" if n[0] == "i" else "-", st.alt, Const(1))
        elif n in ("inc", "dec", "inc.s", "dec.s", "inc.i", "dec.i"):
            op = "++" if n[0] == "i" else "--"
            if n.endswith(".s"):
                t = self.frame(st, out, o)
            elif n.endswith(".i"):
                t = self.deref(st.pri)
            else:
                self.g_scalar.add(o)
                t = G(o)
            top = st.stk[-1] if st.stk else None
            if n.endswith(".i") and top is not None and top.local is None and \
                    isinstance(top.expr, Elem) and top.expr.ia is st.pri:
                # x = array[i]++  (push.pri; load.i; swap.pri; inc.i; pop.pri)
                top.expr = PostInc(t, op)
                st.fx.append(top.expr)
            elif not n.endswith(".i") and self.same_loc(t, st.pri) and not self.tentative:
                st.pri = PostInc(t, op)
                st.fx.append(st.pri)
            else:
                self.emit(st, out, S("expr", e=PostInc(t, op)))
        elif n == "movs":
            self.movs(st, out, o)
        elif n == "fill":
            dst = st.alt
            if isinstance(dst, AddrOf) and isinstance(dst.t, L) and isinstance(st.pri, Const) and st.pri.v == 0:
                pass
            elif isinstance(dst, AddrOf) and isinstance(dst.t, L) and out and out[-1].kind == "decl" \
                    and out[-1].loc is dst.t.loc and out[-1].init is None:
                out[-1].init = S("fill", v=st.pri)
            else:
                self.emit(st, out, S("emit", text="/* fill %d bytes */" % o))
        elif n in ("const", "const.s"):
            if n == "const":
                self.g_scalar.add(ops[0]); self.assign(st, out, G(ops[0]), Const(ops[1]))
            else:
                self.store_frame(st, out, ops[0], Const(ops[1]))
        elif n == "load.both":
            self.g_scalar.add(ops[0]); self.g_scalar.add(ops[1])
            st.pri, st.alt = G(ops[0]), G(ops[1])
        elif n == "load.s.both":
            st.pri, st.alt = self.frame(st, out, ops[0]), self.frame(st, out, ops[1])
        elif n in ("lctrl",):
            st.pri = Raw("/* lctrl %d */ 0" % o)
        else:
            # everything else (sctrl, jump.pri, call.pri, halt, cmps, sysreq.pri ...) as #emit
            self.emit(st, out, S("emit", text="#emit %s %s" % (n, " ".join(str(x) for x in ops))))

    def note_bounds(self, base):
        b = getattr(self, "last_bounds", None)
        if b is not None and isinstance(base, Const):
            self.g_arr[base.v] = max(self.g_arr.get(base.v, 0), b + 1)
        self.last_bounds = None

    def add(self, p, a):
        if isinstance(p, Const) and isinstance(a, Const):
            return Const(p.v + a.v)
        for x, y in ((p, a), (a, p)):
            if isinstance(y, Const) and y.v % self.C == 0 and (
                    isinstance(x, Row) or (isinstance(x, AddrOf) and isinstance(x.t, L) and x.t.loc.size > 1)):
                return IA(x, Const(y.v // self.C))
        for x, y in ((p, a), (a, p)):
            if isinstance(x, Elem) and y is x.ia:
                return Row(x)
            # row 0 of an array parameter: arg[0] (header) + arg
            if isinstance(x, Elem) and isinstance(y, Prm) and isinstance(x.ia.base, Prm) \
                    and x.ia.base.f is y.f and x.ia.base.k == y.k and isinstance(x.ia.idx, Const) \
                    and x.ia.idx.v == 0:
                return Row(x)
            if isinstance(x, Deref) and isinstance(y, Prm) and isinstance(x.a, Prm) \
                    and x.a.f is y.f and x.a.k == y.k:
                return Row(Elem(IA(y, Const(0))))
            if isinstance(x, (G, L)) and isinstance(y, AddrOf) and self.same_loc(x, y.t):
                return Row(x)
            if isinstance(x, G) and isinstance(y, Const) and x.addr == y.v:
                return Row(x)
        if isinstance(a, Const) and a.v < 0:
            return Bin("-", p, Const(-a.v))
        return Bin("+", p, a)

    def char_at(self, e):
        if isinstance(e, Bin) and e.op == "+":
            self.mark_base(e.a)
            return CharAt(e.a, e.b)
        self.mark_base(e)
        return CharAt(e, Const(0))

    def movs(self, st, out, nbytes):
        dst, src = st.alt, st.pri
        if isinstance(dst, HeapTmp):
            self.use(st, src)
            dst.content = src
            return
        if isinstance(dst, AddrOf) and isinstance(dst.t, L) and out and out[-1].kind == "decl" \
                and out[-1].loc is dst.t.loc and out[-1].init is None and not self.tentative:
            self.use(st, src)
            out[-1].init = src
            out[-1].arr = True
            out[-1].init_n = nbytes
            return
        self.emit(st, out, S("expr", e=Assign(dst, src, True)), [src, dst])

    def do_call(self, st, out, o, native, nbytes=None):
        C = self.C
        if nbytes is None:
            cnt = self.pop(st)
            nbytes = cnt.v if isinstance(cnt, Const) else 0
        nargs = max(0, nbytes // C)
        args = [self.pop(st) for _ in range(nargs)]
        if native:
            st.sp -= (nargs + 1) * C if nbytes is not None else 0
            name = self.native_names[o] if 0 <= o < len(self.native_names) else "native_%d" % o
            c = Call(name, args, True)
        else:
            fi = self.fby.get(o)
            c = Call(fi.name if fi else "func_%X" % o, args, False, o)
        self.arg_counts.setdefault(c.name, set()).add(nargs)
        if not native and st.stk and isinstance(st.stk[-1].expr, HeapTmp) and st.stk[-1].local is None:
            st.stk[-1].expr.content = c
        st.fx.append(c)
        st.pri = c

    # ---------------- conditions ----------------
    def jcond(self, st, n):
        if n == "jzer":
            return neg(st.pri) if is_bool(st.pri) else Un("!", st.pri)
        if n == "jnz":
            return st.pri
        return Bin(self.JOP[n], st.pri, st.alt)

    def scan_pure(self, j, e, st, allow_break=True):
        """Simulate expression instructions up to the next control instruction. Returns an index or None."""
        first = j
        save = self.tentative
        self.tentative = True
        try:
            while j < e:
                a, n, ops = self.ins[j]
                if j != first and a in self.labels:
                    return None
                if n == "break" and (j != first or not allow_break):
                    return None
                if n in self.JCOND or n in ("jump", "switch", "casetbl", "retn", "ret"):
                    return j
                self.sim(j, st, [])
                j += 1
            return None
        except ScanFail:
            return None
        finally:
            self.tentative = save

    def explore(self, i, e, st):
        """Walk every path through a pure (statement-free) region of code starting at index i.
        Returns a list of (exit_index, state, decisions) or None."""
        endaddr = self.addr_at(e)
        p0 = Path()
        p0.j, p0.st, p0.dec, p0.seg, p0.segst = i, st.copy(), [], i, st.copy()
        todo, done = [p0], []
        steps = 0
        save = self.tentative, getattr(self, "exploring", False)
        self.tentative = self.exploring = True
        try:
            while todo:
                p = todo.pop()
                while True:
                    steps += 1
                    if steps > 20000 or len(todo) + len(done) > 256:
                        return None
                    j = p.j
                    if j >= e or j < i:
                        done.append((p.seg, p.segst, p.dec))
                        break
                    a, n, ops = self.ins[j]
                    if j != i:
                        if a in self.back_src:
                            if p.seg == j:
                                done.append((p.seg, p.segst, p.dec))
                            else:
                                done.append((j, p.st, p.dec))
                            break
                        if a in self.labels and p.seg != j:
                            p.seg, p.segst = j, p.st.copy()
                    if n == "break":
                        if j == i:
                            p.j += 1
                            p.seg, p.segst = p.j, p.st.copy()
                            continue
                        done.append((p.seg, p.segst, p.dec))
                        break
                    if n in self.JCOND:
                        T = ops[0]
                        if T <= a or T > endaddr:
                            done.append((p.seg, p.segst, p.dec))
                            break
                        c = self.jcond(p.st, n)
                        tv = const_truth(c)
                        if tv is not None:
                            p.j = self.idx(T) if tv else j + 1
                            p.seg, p.segst = p.j, p.st.copy()
                            continue
                        self.use(p.st, c)
                        q = Path()
                        q.j, q.st, q.dec = self.idx(T), p.st.copy(), p.dec + [(c, True)]
                        q.seg, q.segst = q.j, q.st.copy()
                        todo.append(q)
                        p.dec = p.dec + [(c, False)]
                        p.j = j + 1
                        p.seg, p.segst = p.j, p.st.copy()
                        continue
                    if n == "jump":
                        T = ops[0]
                        if T <= a or T > endaddr:
                            done.append((p.seg, p.segst, p.dec))
                            break
                        p.j = self.idx(T)
                        p.seg, p.segst = p.j, p.st.copy()
                        continue
                    if n in ("switch", "casetbl", "retn", "ret"):
                        done.append((p.seg, p.segst, p.dec))
                        break
                    try:
                        self.sim(j, p.st, [])
                    except ScanFail:
                        done.append((p.seg, p.segst, p.dec))
                        break
                    p.j += 1
        finally:
            self.tentative, self.exploring = save
        return done

    def build_tree(self, items, boolean=None):
        """items = [(decisions, list), ...] -> expression."""
        if boolean is None:
            items = [(d, as_cond(v)) for d, v in items]
            boolean = all(v is TRUE or v is FALSE for _, v in items)
        first = items[0][1]
        if all(same(x[1], first) for x in items):
            return first
        if any(not d for d, _ in items):
            raise ScanFail()
        atom = items[0][0][0][0]
        if any(d[0][0] is not atom for d, _ in items):
            raise ScanFail()
        T = [(d[1:], v) for d, v in items if d[0][1]]
        F = [(d[1:], v) for d, v in items if not d[0][1]]
        if not T or not F:
            return self.build_tree(T or F, boolean)
        A, B = self.build_tree(T, boolean), self.build_tree(F, boolean)
        return cond_tern(atom, A, B) if boolean else val_tern(atom, A, B)

    def region(self, i, e, st):
        """Result: ('value', X, state) | ('if', E, B, Bst, F, Fst) | None"""
        done = self.explore(i, e, st)
        if not done or len(done) < 2 and not any(d for _, _, d in done):
            return None
        clear_key_cache()
        exits = {}
        for x, s2, dec in done:
            exits.setdefault(x, []).append((s2, dec))
        try:
            if len(exits) == 1:
                X = list(exits)[0]
                lst = exits[X]
                s0 = lst[0][0]
                for s2, _ in lst:
                    if len(s2.stk) != len(s0.stk) or s2.sp != s0.sp or \
                            any(a is not b for a, b in zip(s2.stk, s0.stk)):
                        return None
                    # a side effect (e.g. a call) that does not end up in the value
                    # would be lost by merging the paths: keep this an if statement
                    for f in s2.fx:
                        if not any(f is g for g in st.fx) and \
                                not any(x is f for v in (s2.pri, s2.alt) for x in iter_nodes(v)):
                            return None
                m = s0.copy()
                m.pri = as_val(self.build_tree([(d, s2.pri) for s2, d in lst]))
                if any(s2.alt is not s0.alt for s2, _ in lst):
                    m.alt = as_val(self.build_tree([(d, s2.alt) for s2, d in lst]))
                m.fx = list(st.fx)
                # the merged value carries the paths' side effects: keep it pending so
                # it is still written out if nothing uses the value
                if any(not any(f is g for g in st.fx) for s2, _ in lst for f in s2.fx):
                    m.fx.append(m.pri)
                return ("value", X, m)
            if len(exits) == 2:
                B, F = sorted(exits)
                items = [(d, TRUE) for _, d in exits[B]] + [(d, FALSE) for _, d in exits[F]]
                E = self.build_tree(items)
                if E is TRUE or E is FALSE:
                    return None
                bst, fst = exits[B][0][0], exits[F][0][0]
                if len(bst.stk) != len(fst.stk) or bst.sp != fst.sp:
                    return None
                return ("if", E, B, bst, F, fst)
        except (ScanFail, RecursionError):
            return None
        return None

    def parse_chain(self, j, e, st):
        """j = index of a conditional jump. Folds a chain of jumps into one condition (&&, ||).
        Returns (condition_for_body, last, F, state)."""
        chain = [(j, self.jcond(st, self.ins[j][1]), self.ins[j][2][0], st, None)]
        cur = st
        while True:
            last = chain[-1][0]
            s2 = cur.copy()
            k = self.scan_pure(last + 1, e, s2, allow_break=False)
            if k is None or self.ins[k][1] not in self.JCOND:
                break
            chain.append((k, self.jcond(s2, self.ins[k][1]), self.ins[k][2][0], s2,
                          self.addr_at(last + 1)))
            cur = s2
        for p in range(len(chain), 0, -1):
            lastk, lastc, F, lst, _ = chain[p - 1]
            body = self.addr_at(lastk + 1)
            if F <= body and p > 1:
                continue
            seg = {chain[m][4]: m for m in range(1, p)}
            ok = True
            for q in range(p - 1):
                t = chain[q][2]
                if not (t == F or t == body or (t in seg and seg[t] > q)):
                    ok = False
                    break
            if not ok:
                continue
            R = [None] * (p + 1)
            R[p] = TRUE
            for q in range(p - 1, -1, -1):
                t = chain[q][2]
                A = TRUE if t == body else FALSE if t == F else R[seg[t]]
                R[q] = cond_tern(chain[q][1], A, R[q + 1])
            return R[0], lastk, F, lst
        raise AssertionError

    # ---------------- structuring ----------------
    def jump_stmt(self, T, ctx):
        if T == ctx.get("brk"):
            return S("break")
        if T == ctx.get("cont"):
            return S("continue")
        self.gotos.add(T)
        return S("goto", t=T)

    def block(self, s, e, st, ctx, skip_loop=None):
        out = []
        i = s
        while i < e:
            addr, n, ops = self.ins[i]
            if addr in self.goto_targets and i != skip_loop:
                self.flush_fx(st, out)
                out.append(S("label", t=addr))
            if addr in self.back_src and i != skip_loop:
                srcs = [q for q in self.back_src[addr] if i <= q < e]
                if srcs:
                    i = self.do_loop(i, max(srcs), st, out, ctx)
                    continue
            if n == "break":
                self.flush_fx(st, out)
                self.declare_pending(st, out)
                i += 1
            elif n in self.JCOND:
                i = self.do_if(i, e, st, out, ctx)
            elif n == "jump":
                i = self.do_jump(i, e, st, out, ctx)
            elif n == "switch":
                i = self.do_switch(i, st, out, ctx)
            elif n in ("retn", "ret"):
                v = st.pri
                self.emit(st, out, S("return", e=v), [v])
                i += 1
            elif n == "casetbl":
                i += 1
            else:
                self.sim(i, st, out)
                i += 1
        if not self.tentative:
            self.flush_fx(st, out)
        return out

    def do_if(self, i, e, st, out, ctx):
        T = self.ins[i][2][0]
        endaddr = self.addr_at(e)
        reg = self.region(i, e, st)
        if reg and reg[0] == "value":
            _, X, m = reg
            st.pri, st.alt, st.stk, st.sp, st.fx = m.pri, m.alt, m.stk, m.sp, m.fx
            return X
        if reg and reg[0] == "if":
            _, E, B, bst, F, fst = reg
            return self.make_if(E, B, bst, F, fst, e, st, out, ctx)
        if not (self.ins[i][0] < T <= endaddr):
            c = self.jcond(st, self.ins[i][1])
            self.emit(st, out, S("if", c=c, then=[self.jump_stmt(T, ctx)], els=None), [c])
            return i + 1
        E, last, F, st2 = self.parse_chain(i, e, st)
        if not (self.ins[last][0] < F <= endaddr):
            E, last, F, st2 = neg(self.jcond(st, self.ins[i][1])), i, T, st
        fk = self.idx(F)
        then_end, els_rng, cont = fk, None, fk
        if fk - 1 > last and self.ins[fk - 1][1] == "jump":
            U = self.ins[fk - 1][2][0]
            if F < U <= endaddr:
                then_end, els_rng, cont = fk - 1, (fk, self.idx(U)), self.idx(U)
        s_then = st2.copy(freeze=True)
        then = self.block(last + 1, then_end, s_then, ctx)
        els, s_els = None, None
        if els_rng:
            s_els = st2.copy(freeze=True)
            els = self.block(els_rng[0], els_rng[1], s_els, ctx)
        # ternary operator / && || used as a value
        if els_rng and not then and not els and s_then.pri is not st2.pri and s_els.pri is not st2.pri \
                and len(s_then.stk) == len(st2.stk) == len(s_els.stk):
            a, b = s_then.pri, s_els.pri
            if isinstance(a, Const) and isinstance(b, Const) and a.v == 1 and b.v == 0 and is_bool(E):
                v = E
            elif isinstance(a, Const) and isinstance(b, Const) and a.v == 0 and b.v == 1 and is_bool(E):
                v = neg(E)
            else:
                v = Tern(E, a, b)
            st.pri, st.alt, st.stk, st.sp = v, st2.alt, list(st2.stk), st2.sp
            st.fx = list(st2.fx)
            if s_then.fx or s_els.fx:
                st.fx.append(v)
            return cont
        st.pri, st.alt, st.stk, st.sp, st.fx = st2.pri, st2.alt, list(st2.stk), st2.sp, list(st2.fx)
        if not then and els:
            E, then, els = neg(E), els, None
        self.emit(st, out, S("if", c=E, then=then, els=els), [E])
        return cont

    def make_if(self, E, bk, bst, fk, fst, e, st, out, ctx):
        endaddr = self.addr_at(e)
        F = self.addr_at(fk)
        then_end, els_rng, cont = fk, None, fk
        if fk - 1 >= bk and self.ins[fk - 1][1] == "jump":
            U = self.ins[fk - 1][2][0]
            if F < U <= endaddr:
                then_end, els_rng, cont = fk - 1, (fk, self.idx(U)), self.idx(U)
        s_then = bst.copy(freeze=True)
        s_then.frozen = min(s_then.frozen, len(st.stk))
        then = self.block(bk, then_end, s_then, ctx)
        els = None
        if els_rng:
            s_els = fst.copy(freeze=True)
            s_els.frozen = min(s_els.frozen, len(st.stk))
            els = self.block(els_rng[0], els_rng[1], s_els, ctx)
        if not then and els:
            E, then, els = neg(E), els, None
        self.emit(st, out, S("if", c=E, then=then, els=els), [E])
        st.pri, st.alt = fst.pri, fst.alt
        return cont

    def do_loop(self, i, q, st, out, ctx):
        exit_a = self.addr_at(q + 1)
        head = self.ins[i][0]
        n = self.ins[q][1]
        if n == "jump":
            lctx = dict(ctx, brk=exit_a, cont=head)
            reg = self.region(i, q + 1, st)
            if reg and reg[0] == "if" and self.addr_at(reg[4]) == exit_a:
                _, E, B, bst, F, fst = reg
                body = self.block(B, q, bst.copy(freeze=True), lctx)
                self.emit(st, out, S("while", c=E, body=body), [E])
                return q + 1
            s2 = st.copy()
            j = self.scan_pure(i, q, s2)
            if j is not None and self.ins[j][1] in self.JCOND and self.ins[j][2][0] == exit_a:
                E, last, F, s3 = self.parse_chain(j, q, s2)
                if F == exit_a:
                    body = self.block(last + 1, q, s3.copy(freeze=True), lctx)
                    self.emit(st, out, S("while", c=E, body=body), [E])
                    return q + 1
            body = self.block(i, q, st.copy(freeze=True), lctx, skip_loop=i)
            self.emit(st, out, S("while", c=Const(1), body=body))
            return q + 1
        # do { } while (c)
        lctx = dict(ctx, brk=exit_a, cont=None)
        s2 = st.copy(freeze=True)
        body = self.block(i, q, s2, lctx, skip_loop=i)
        c = self.jcond(s2, n)
        self.emit(st, out, S("do", c=c, body=body), [c])
        return q + 1

    def do_jump(self, i, e, st, out, ctx):
        T = self.ins[i][2][0]
        h = i + 1
        if h < e and T > self.ins[i][0]:
            ha = self.ins[h][0]
            srcs = [q for q in self.back_src.get(ha, []) if h <= q < e]
            if srcs:
                q = max(srcs)
                if self.ins[q][1] == "jump" and ha < T <= self.ins[q][0]:
                    return self.do_for(i, h, self.idx(T), q, st, out, ctx)
        if T == self.addr_at(i + 1):
            return i + 1
        if T == ctx.get("sw_end") and i == ctx.get("sw_last"):
            return i + 1
        self.emit(st, out, self.jump_stmt(T, ctx))
        return i + 1

    def do_for(self, i, h, tk, q, st, out, ctx):
        exit_a = self.addr_at(q + 1)
        lctx = dict(ctx, brk=exit_a, cont=self.ins[h][0])
        self.declare_pending(st, out)
        self.flush_fx(st, out)
        inc = self.block(h, tk, st.copy(freeze=True), {})
        s2 = st.copy()
        E, bstart = None, tk
        reg = self.region(tk, q + 1, st)
        j = None
        if reg and reg[0] == "if" and self.addr_at(reg[4]) == exit_a:
            E, bstart, s2 = reg[1], reg[2], reg[3]
        else:
            j = self.scan_pure(tk, q, s2)
        if j is not None and self.ins[j][1] in self.JCOND:
            E2, last, F, s3 = self.parse_chain(j, q, s2)
            if F == exit_a:
                E, bstart, s2 = E2, last + 1, s3
            else:
                s2 = st.copy()
        else:
            s2 = st.copy()
        body = self.block(bstart, q, s2.copy(freeze=True), lctx)
        init = None
        if out and out[-1].kind == "decl" and q + 1 < len(self.ins) and self.ins[q + 1][1] == "stack":
            init = out.pop()
        self.emit(st, out, S("for", init=init, c=E, inc=inc, body=body), [E] if E else [])
        return q + 1

    def do_switch(self, i, st, out, ctx):
        T = self.ins[i][2][0]
        t = self.idx(T)
        expr = st.pri
        self.use(st, expr)
        tops = self.ins[t][2]
        cnt, dflt = tops[0], tops[1]
        end_a = self.addr_at(t + 1)
        tg = {}
        for c in range(cnt):
            tg.setdefault(tops[3 + 2 * c], []).append(tops[2 + 2 * c])
        alltg = sorted(set(tg) | ({dflt} if dflt != end_a else set()))
        self.declare_pending(st, out)
        self.flush_fx(st, out)
        cases = []
        for k, ta in enumerate(alltg):
            s2 = self.idx(ta)
            e2 = self.idx(alltg[k + 1]) if k + 1 < len(alltg) else t
            c2 = dict(ctx, sw_end=end_a, sw_last=e2 - 1)
            body = self.block(s2, e2, st.copy(freeze=True), c2)
            vals = sorted(tg.get(ta, []))
            cases.append((vals, ta == dflt, body))
        self.emit(st, out, S("switch", e=expr, cases=cases), [])
        return t + 1

    # ---------------- functions ----------------
    def build(self, fi):
        self.cur = fi
        self.cur_written = {x[2][0] for x in self.ins[fi.k0 + 1:fi.k1]
                            if x[1] in ("stor.s.pri", "stor.s.alt", "inc.s", "dec.s", "zero.s",
                                        "addr.pri", "addr.alt") and x[2]}
        self.tentative = False
        self.goto_targets = set()
        for _ in range(4):
            self.gotos = set()
            fi.nloc = 0
            st = State()
            st.pri = Const(0)
            st.alt = Const(0)
            st.stk, st.sp, st.fx, st.frozen = [], 0, [], 0
            self.last_bounds = None
            body = self.block(fi.k0 + 1, fi.k1, st, {})
            if self.gotos <= self.goto_targets:
                break
            self.goto_targets |= self.gotos
        fi.body = body
        rets = []
        self._collect(body, "return", rets)
        fi.ret_value = any(not (isinstance(r.e, Const) and r.e.v == 0) for r in rets)

    def _collect(self, stmts, kind, acc):
        for s in stmts:
            if s.kind == kind:
                acc.append(s)
            for sub in ("then", "els", "body", "inc"):
                v = getattr(s, sub, None)
                if isinstance(v, list):
                    self._collect(v, kind, acc)
            if s.kind == "switch":
                for _, _, b in s.cases:
                    self._collect(b, kind, acc)

    def run(self):
        for fi in self.funcs:
            try:
                self.build(fi)
            except Exception as ex:   # never fail the whole file because of one function
                fi.body = [S("emit", text="/* DECOMPILATION FAILED: %s - see the .asm listing */" % ex)]
                fi.failed = True
        return self
