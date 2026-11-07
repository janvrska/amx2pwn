"""Expression and statement tree used by the decompiler and the renderer."""


class ScanFail(Exception):
    pass


# ---------------------------- expressions ----------------------------------
class N:
    __slots__ = ()

    def kids(self):
        return ()


class Const(N):
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


class G(N):          # global variable (value) at an address
    __slots__ = ("addr",)

    def __init__(self, addr):
        self.addr = addr


class Prm(N):        # function parameter
    __slots__ = ("f", "k")

    def __init__(self, f, k):
        self.f, self.k = f, k


class L(N):          # local variable (k = element index for arrays)
    __slots__ = ("loc", "k")

    def __init__(self, loc, k=None):
        self.loc, self.k = loc, k


class AddrOf(N):
    __slots__ = ("t",)

    def __init__(self, t):
        self.t = t

    def kids(self):
        return (self.t,)


class IA(N):         # address of an array element: base[idx]
    __slots__ = ("base", "idx")

    def __init__(self, base, idx):
        self.base, self.idx = base, idx

    def kids(self):
        return (self.base, self.idx)


class Elem(N):       # value of an array element: base[idx]
    __slots__ = ("ia",)

    def __init__(self, ia):
        self.ia = ia

    def kids(self):
        return (self.ia,)


class Row(N):        # row of a 2D array (an address) - x is an Elem/G/L with a row header
    __slots__ = ("x",)

    def __init__(self, x):
        self.x = x

    def kids(self):
        return (self.x,)


class CharAt(N):
    __slots__ = ("base", "idx")

    def __init__(self, base, idx):
        self.base, self.idx = base, idx

    def kids(self):
        return (self.base, self.idx)


class Deref(N):
    __slots__ = ("a",)

    def __init__(self, a):
        self.a = a

    def kids(self):
        return (self.a,)


class Bin(N):
    __slots__ = ("op", "a", "b")

    def __init__(self, op, a, b):
        self.op, self.a, self.b = op, a, b

    def kids(self):
        return (self.a, self.b)


class Un(N):
    __slots__ = ("op", "a")

    def __init__(self, op, a):
        self.op, self.a = op, a

    def kids(self):
        return (self.a,)


class Call(N):
    __slots__ = ("name", "args", "native", "faddr")

    def __init__(self, name, args, native, faddr=None):
        self.name, self.args, self.native, self.faddr = name, args, native, faddr

    def kids(self):
        return tuple(self.args)


class Tern(N):
    __slots__ = ("c", "a", "b")

    def __init__(self, c, a, b):
        self.c, self.a, self.b = c, a, b

    def kids(self):
        return (self.c, self.a, self.b)


class PostInc(N):
    __slots__ = ("t", "op")

    def __init__(self, t, op):
        self.t, self.op = t, op

    def kids(self):
        return (self.t,)


class Assign(N):
    __slots__ = ("t", "v", "arr")

    def __init__(self, t, v, arr=False):
        self.t, self.v, self.arr = t, v, arr

    def kids(self):
        return (self.t, self.v)


class HeapTmp(N):
    __slots__ = ("content",)

    def __init__(self):
        self.content = None

    def kids(self):
        return (self.content,) if self.content is not None else ()


class Raw(N):
    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text


CMP_OPS = {"==", "!=", "<", "<=", ">", ">="}

REL_OPS = {"<", "<=", ">", ">="}

INV = {"==": "!=", "!=": "==", "<": ">=", ">=": "<", ">": "<=", "<=": ">"}


# Pawn precedence: & ^ | bind tighter than comparisons (unlike C)
PREC = {"*": 13, "/": 13, "%": 13, "+": 12, "-": 12, "<<": 11, ">>": 11, ">>>": 11,
        "&": 10, "^": 9, "|": 8, "<": 7, "<=": 7, ">": 7, ">=": 7, "==": 6, "!=": 6,
        "&&": 5, "||": 4}


def is_bool(e):
    return (isinstance(e, Bin) and (e.op in CMP_OPS or e.op in ("&&", "||"))) or \
        (isinstance(e, Un) and e.op == "!")


def neg(c):
    if isinstance(c, Un) and c.op == "!":
        return c.a
    if isinstance(c, Bin) and c.op in INV:
        return Bin(INV[c.op], c.a, c.b)
    if isinstance(c, Bin) and c.op in ("&&", "||"):
        return Bin("||" if c.op == "&&" else "&&", neg(c.a), neg(c.b))
    if isinstance(c, Tern):
        return Tern(c.c, neg(c.a), neg(c.b))
    return Un("!", c)


TRUE, FALSE = Raw("true"), Raw("false")

_SKEY = {}   # id(node) -> (node, key) cache for skey()


def clear_key_cache():
    _SKEY.clear()


def skey(e):
    if e is None:
        return None
    k = _SKEY.get(id(e))
    if k is not None and k[0] is e:
        return k[1]
    r = _skey(e)
    _SKEY[id(e)] = (e, r)
    return r


def _skey(e):
    if isinstance(e, Const):
        return ("c", e.v)
    if isinstance(e, G):
        return ("g", e.addr)
    if isinstance(e, Prm):
        return ("p", id(e.f), e.k)
    if isinstance(e, L):
        return ("l", id(e.loc), e.k)
    if isinstance(e, Raw):
        return ("r", e.text)
    if isinstance(e, Bin):
        return ("b", e.op, skey(e.a), skey(e.b))
    if isinstance(e, Un):
        return ("u", e.op, skey(e.a))
    if isinstance(e, Call):
        return ("call", e.name, e.faddr, tuple(skey(x) for x in e.args))
    if isinstance(e, HeapTmp):
        return ("h", skey(e.content))
    return (type(e).__name__,) + tuple(skey(k) for k in e.kids())


def same(a, b):
    return a is b or skey(a) == skey(b)


def cond_tern(c, A, B):
    """Condition 'c ? A : B' simplified to && / ||."""
    if A is TRUE and B is FALSE:
        return c
    if A is FALSE and B is TRUE:
        return neg(c)
    if A is TRUE:
        return Bin("||", c, B)
    if A is FALSE:
        return Bin("&&", neg(c), B)
    if B is TRUE:
        return Bin("||", neg(c), A)
    if B is FALSE:
        return Bin("&&", c, A)
    if isinstance(B, Bin) and B.op == "&&" and same(B.b, A):
        return Bin("&&", Bin("||", c, B.a), A)
    if isinstance(B, Bin) and B.op == "||" and same(B.b, A):
        return Bin("||", Bin("&&", neg(c), B.a), A)
    if isinstance(A, Bin) and A.op == "&&" and same(A.b, B):
        return Bin("&&", Bin("||", neg(c), A.a), B)
    if isinstance(A, Bin) and A.op == "||" and same(A.b, B):
        return Bin("||", Bin("&&", c, A.a), B)
    if same(A, B):
        return A
    return Tern(c, A, B)


def as_val(x):
    if x is TRUE:
        return Const(1)
    if x is FALSE:
        return Const(0)
    return x


def as_cond(x):
    if isinstance(x, Const) and x.v in (0, 1):
        return TRUE if x.v else FALSE
    return x


def val_tern(c, A, B):
    a, b = as_cond(A), as_cond(B)
    if (a in (TRUE, FALSE) or is_bool(a)) and (b in (TRUE, FALSE) or is_bool(b)):
        return cond_tern(c, a, b)
    if same(A, B):
        return A
    return Tern(c, as_val(A), as_val(B))


def const_truth(c):
    """Evaluate a condition over constants, otherwise None."""
    if isinstance(c, Const):
        return c.v != 0
    if isinstance(c, Un) and c.op == "!":
        t = const_truth(c.a)
        return None if t is None else not t
    if isinstance(c, Bin) and c.op in CMP_OPS and isinstance(c.a, Const) and isinstance(c.b, Const):
        x, y = c.a.v, c.b.v
        return {"==": x == y, "!=": x != y, "<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[c.op]
    return None


class Path:
    __slots__ = ("j", "st", "dec", "seg", "segst")


# ---------------------------- statements -----------------------------------
class Local:
    __slots__ = ("name", "size", "dims")

    def __init__(self, name, size):
        self.name, self.size = name, size
        self.dims = None


class Item:
    __slots__ = ("off", "expr", "size", "local")

    def __init__(self, off, expr, size=1):
        self.off, self.expr, self.size, self.local = off, expr, size, None


class State:
    __slots__ = ("pri", "alt", "stk", "sp", "fx", "frozen")

    def copy(self, freeze=False):
        s = State()
        s.pri, s.alt, s.sp = self.pri, self.alt, self.sp
        s.stk = list(self.stk)
        s.fx = [] if freeze else list(self.fx)
        s.frozen = len(self.stk) if freeze else self.frozen
        return s


class S:
    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)


class FuncInfo:
    def __init__(self, addr, name, public):
        self.addr, self.name, self.public = addr, name, public
        self.nparams = 0
        self.pkind = {}       # k -> 'a' (array) | 'r' (reference)
        self.pnames = {}
        self.body = []
        self.ret_value = False
        self.value_used = False
        self.used_params = set()
        self.nloc = 0


# float natives that have an operator form
FOPS = {"floatadd": "+", "floatsub": "-", "floatmul": "*", "floatdiv": "/"}

OVL_OPS = {"+", "-", "*", "/"} | CMP_OPS

FLOAT_NATIVES = {"float", "floatadd", "floatsub", "floatmul", "floatdiv", "floatcmp", "floatround",
                 "floatsqroot", "floatpower", "floatlog", "floatsin", "floatcos", "floattan", "floatabs",
                 "floatfract", "floatstr"}


def subst(e, args, fi):
    """Substitute call arguments for the template parameters."""
    if isinstance(e, Prm) and e.f is fi:
        return args[e.k] if e.k < len(args) else Const(0)
    if isinstance(e, Call):
        return Call(e.name, [subst(x, args, fi) for x in e.args], e.native, e.faddr)
    if isinstance(e, Bin):
        return Bin(e.op, subst(e.a, args, fi), subst(e.b, args, fi))
    if isinstance(e, Un):
        return Un(e.op, subst(e.a, args, fi))
    return e


def iter_stmts(stmts):
    for st in stmts:
        yield st
        for sub in ("then", "els", "body", "inc"):
            v = getattr(st, sub, None)
            if isinstance(v, list):
                for x in iter_stmts(v):
                    yield x
        if st.kind == "for" and getattr(st, "init", None) is not None:
            for x in iter_stmts([st.init]):
                yield x
        if st.kind == "switch":
            for _, _, b in st.cases:
                for x in iter_stmts(b):
                    yield x


def stmt_roots(st):
    return [getattr(st, a) for a in ("e", "c", "init") if isinstance(getattr(st, a, None), N)]


def iter_nodes(e):
    stack = [e]
    while stack:
        x = stack.pop()
        if x is None or not isinstance(x, N):
            continue
        yield x
        stack.extend(x.kids())
