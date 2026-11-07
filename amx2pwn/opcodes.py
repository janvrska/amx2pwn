"""Pawn AMX opcode table (Pawn 3.x; SA-MP and open.mp use the same encoding)."""


# --------------------------------------------------------------------------
# Opcodes (Pawn 3.x; SA-MP uses 3.2, open.mp / pawn-lang 3.10 use the same set)
# value = number of operands; -1 = special (casetbl), -2 = file/symbol (variable length)
# --------------------------------------------------------------------------
OPCODES = [
    ("none", 0), ("load.pri", 1), ("load.alt", 1), ("load.s.pri", 1), ("load.s.alt", 1),
    ("lref.pri", 1), ("lref.alt", 1), ("lref.s.pri", 1), ("lref.s.alt", 1), ("load.i", 0),
    ("lodb.i", 1), ("const.pri", 1), ("const.alt", 1), ("addr.pri", 1), ("addr.alt", 1),
    ("stor.pri", 1), ("stor.alt", 1), ("stor.s.pri", 1), ("stor.s.alt", 1), ("sref.pri", 1),
    ("sref.alt", 1), ("sref.s.pri", 1), ("sref.s.alt", 1), ("stor.i", 0), ("strb.i", 1),
    ("lidx", 0), ("lidx.b", 1), ("idxaddr", 0), ("idxaddr.b", 1), ("align.pri", 1),
    ("align.alt", 1), ("lctrl", 1), ("sctrl", 1), ("move.pri", 0), ("move.alt", 0),
    ("xchg", 0), ("push.pri", 0), ("push.alt", 0), ("push.r", 1), ("push.c", 1),
    ("push", 1), ("push.s", 1), ("pop.pri", 0), ("pop.alt", 0), ("stack", 1),
    ("heap", 1), ("proc", 0), ("ret", 0), ("retn", 0), ("call", 1),
    ("call.pri", 0), ("jump", 1), ("jrel", 1), ("jzer", 1), ("jnz", 1),
    ("jeq", 1), ("jneq", 1), ("jless", 1), ("jleq", 1), ("jgrtr", 1),
    ("jgeq", 1), ("jsless", 1), ("jsleq", 1), ("jsgrtr", 1), ("jsgeq", 1),
    ("shl", 0), ("shr", 0), ("sshr", 0), ("shl.c.pri", 1), ("shl.c.alt", 1),
    ("shr.c.pri", 1), ("shr.c.alt", 1), ("smul", 0), ("sdiv", 0), ("sdiv.alt", 0),
    ("umul", 0), ("udiv", 0), ("udiv.alt", 0), ("add", 0), ("sub", 0),
    ("sub.alt", 0), ("and", 0), ("or", 0), ("xor", 0), ("not", 0),
    ("neg", 0), ("invert", 0), ("add.c", 1), ("smul.c", 1), ("zero.pri", 0),
    ("zero.alt", 0), ("zero", 1), ("zero.s", 1), ("sign.pri", 0), ("sign.alt", 0),
    ("eq", 0), ("neq", 0), ("less", 0), ("leq", 0), ("grtr", 0),
    ("geq", 0), ("sless", 0), ("sleq", 0), ("sgrtr", 0), ("sgeq", 0),
    ("eq.c.pri", 1), ("eq.c.alt", 1), ("inc.pri", 0), ("inc.alt", 0), ("inc", 1),
    ("inc.s", 1), ("inc.i", 0), ("dec.pri", 0), ("dec.alt", 0), ("dec", 1),
    ("dec.s", 1), ("dec.i", 0), ("movs", 1), ("cmps", 1), ("fill", 1),
    ("halt", 1), ("bounds", 1), ("sysreq.pri", 0), ("sysreq.c", 1), ("file", -2),
    ("line", 2), ("symbol", -2), ("srange", 2), ("jump.pri", 0), ("switch", 1),
    ("casetbl", -1), ("swap.pri", 0), ("swap.alt", 0), ("push.adr", 1), ("nop", 0),
    ("sysreq.n", 2), ("symtag", 1), ("break", 0),
    # macro instructions (Pawn 3.3+)
    ("push2.c", 2), ("push2", 2), ("push2.s", 2), ("push2.adr", 2),
    ("push3.c", 3), ("push3", 3), ("push3.s", 3), ("push3.adr", 3),
    ("push4.c", 4), ("push4", 4), ("push4.s", 4), ("push4.adr", 4),
    ("push5.c", 5), ("push5", 5), ("push5.s", 5), ("push5.adr", 5),
    ("load.both", 2), ("load.s.both", 2), ("const", 2), ("const.s", 2),
    ("sysreq.d", 1), ("sysreq.nd", 2),
]

OP = {name: i for i, (name, _) in enumerate(OPCODES)}

JUMPS = {"jump", "jzer", "jnz", "jeq", "jneq", "jless", "jleq", "jgrtr", "jgeq",
         "jsless", "jsleq", "jsgrtr", "jsgeq"}


# operand is an address in the data segment (global variable)
DATA_OPS = {"load.pri", "load.alt", "lref.pri", "lref.alt", "stor.pri", "stor.alt",
            "sref.pri", "sref.alt", "push", "inc", "dec", "zero"}


# operand is a frame offset (local variable / parameter)
FRAME_OPS = {"load.s.pri", "load.s.alt", "lref.s.pri", "lref.s.alt", "addr.pri", "addr.alt",
             "stor.s.pri", "stor.s.alt", "sref.s.pri", "sref.s.alt", "push.s", "push.adr",
             "inc.s", "dec.s", "zero.s"}
