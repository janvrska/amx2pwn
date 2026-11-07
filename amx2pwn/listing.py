"""Disassembler: the .asm listing and the --emit output (function bodies as #emit)."""

from .amxfile import AMX_FLAG_COMPACT
from .literals import float_str, looks_float, pawn_str
from .opcodes import DATA_OPS, FRAME_OPS, JUMPS


class Disassembler:
    def __init__(self, amx):
        self.a = amx
        self.ins = amx.disassemble()
        self.strings = amx.find_strings()
        self.C = amx.cell
        self._names()
        self._functions()

    # ------------- naming -------------
    def _names(self):
        a = self.a
        self.func_names = {}
        self.global_names = {}
        self.local_names = {}  # (func_addr, offset) -> name
        self.func_params_dbg = {}
        for addr, name in a.public_list:
            self.func_names[addr] = name
        if a.cip >= 0 and a.cip not in self.func_names:
            self.func_names[a.cip] = "main"
        for addr, name in a.pubvar_list:
            self.global_names[addr] = name
        for s in a.dbg_symbols:
            if s["ident"] == 9:  # function
                self.func_names.setdefault(s["addr"], s["name"])
            elif s["vclass"] in (0, 2) and s["cs"] == 0 or s["vclass"] == 0:
                self.global_names.setdefault(s["addr"], s["name"])
        self.dbg_locals = [s for s in a.dbg_symbols if s["ident"] != 9 and s["vclass"] == 1]

    def gname(self, addr):
        if addr in self.global_names:
            return self.global_names[addr]
        return "g_%X" % addr

    def fname(self, addr):
        return self.func_names.get(addr, "func_%X" % addr)

    def native(self, idx):
        if 0 <= idx < len(self.a.native_list):
            return self.a.native_list[idx]
        return "native_%d" % idx

    def frame_name(self, func, off, cip=None):
        for s in self.dbg_locals:
            if s["addr"] == off and (cip is None or s["cs"] <= cip < s["ce"] + 2 * self.C):
                return s["name"]
        if off >= 3 * self.C:
            return "arg%d" % ((off - 3 * self.C) // self.C)
        if off < 0:
            return "var%d" % (-off // self.C - 1)
        return "frm[%d]" % off

    # ------------- functions -------------
    def _functions(self):
        self.funcs = []  # (start_index, end_index, addr)
        starts = [k for k, (_, n, _) in enumerate(self.ins) if n == "proc"]
        for j, k in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else len(self.ins)
            self.funcs.append((k, end, self.ins[k][0]))
        self.labels = set()
        for addr, n, ops in self.ins:
            if n in JUMPS:
                self.labels.add(ops[0])
            elif n == "casetbl":
                self.labels.add(ops[1])
                for t in range(ops[0]):
                    self.labels.add(ops[3 + 2 * t])
        # global arrays: [bounds N] const.alt X -> lidx/idxaddr/load.i/...
        self.arrays = {}
        idx_ops = {"lidx", "idxaddr", "lidx.b", "idxaddr.b", "load.i", "stor.i", "movs", "fill"}
        for k in range(len(self.ins) - 1):
            a0, n0, o0 = self.ins[k]
            if n0 not in ("const.alt", "const.pri") or not (0 <= o0[0] < len(self.a.data)) \
                    or o0[0] % self.C:
                continue
            X = o0[0]
            nxt = [self.ins[t][1] for t in range(k + 1, min(k + 4, len(self.ins)))]
            size = None
            for t in range(k + 1, min(k + 4, len(self.ins) - 1)):
                if self.ins[t][1] == "bounds" and self.ins[t + 1][1] in idx_ops:
                    size = self.ins[t][2][0] + 1
                    break
            if size is None and nxt and nxt[0] in idx_ops and X >= 0x100:
                size = 0
            if size is not None:
                self.arrays[X] = max(size, self.arrays.get(X, 0))
        # addresses below 0x100 are strings only when string natives use them
        self.str_refs = set()
        self.callers = {}
        for addr, n, ops in self.ins:
            if n == "call":
                self.callers.setdefault(ops[0], 0)
                self.callers[ops[0]] += 1

    # ------------- operand descriptions -------------
    def is_str(self, v):
        return v in self.strings and (v >= 0x100 or v in self.str_refs)

    def const_repr(self, v):
        if v in self.arrays:
            return self.gname(v)
        if self.is_str(v):
            return pawn_str(self.strings[v])
        if v == -1:
            return "-1"
        if looks_float(v) and abs(v) > 0x100000:
            return float_str(v)
        if abs(v) > 0xFFFFF:
            return "0x%08X" % (v & 0xFFFFFFFF)
        return str(v)

    def push_repr(self, func, cip, name, op):
        if name.endswith(".c"):
            return self.const_repr(op)
        if name.endswith(".adr"):
            return self.frame_name(func, op, cip)
        if name.endswith(".s"):
            return self.frame_name(func, op, cip)
        return self.gname(op)

    def comment(self, func, k):
        addr, n, ops = self.ins[k]
        if n == "sysreq.c" or n == "sysreq.n":
            return self._call_repr(func, k, self.native(ops[0]))
        if n == "call":
            return self._call_repr(func, k, self.fname(ops[0]))
        if n in ("push.c", "const.pri", "const.alt") and self.is_str(ops[0]):
            return pawn_str(self.strings[ops[0]])
        if n in ("const.pri", "const.alt") and ops[0] in self.arrays:
            return self.gname(ops[0])
        if n in DATA_OPS:
            if ops[0] in self.strings:
                return "%s = %s" % (self.gname(ops[0]), pawn_str(self.strings[ops[0]]))
            return self.gname(ops[0])
        if n in FRAME_OPS:
            return self.frame_name(func, ops[0], addr)
        if n in ("push.c", "const.pri", "const.alt", "eq.c.pri", "eq.c.alt", "add.c") and looks_float(ops[0]):
            return float_str(ops[0]) + " ?"
        return ""

    def _call_repr(self, func, k, fname):
        """Walk the pushes before a call backwards and rebuild its arguments."""
        args = []
        j = k - 1
        nbytes = None
        addr, n, ops = self.ins[k]
        if n == "sysreq.n":
            nbytes = ops[1]
        else:
            if j >= 0 and self.ins[j][1] == "push.c":
                nbytes = self.ins[j][2][0]
                j -= 1
        if nbytes is None or nbytes < 0 or nbytes % self.C:
            return "%s(...)" % fname
        need = nbytes // self.C
        while need > 0 and j >= 0:
            a2, n2, o2 = self.ins[j]
            if n2.startswith("push") and n2 not in ("push.pri", "push.alt", "push.r"):
                kind = n2[n2.index("."):] if "." in n2 else ""
                if n2[:5] in ("push2", "push3", "push4", "push5"):
                    kind = n2[5:]
                    plain = "push" + kind
                    vals = [self.push_repr(func, a2, plain, x) for x in o2]
                else:
                    vals = [self.push_repr(func, a2, n2, o2[0])]
                for v in reversed(vals):
                    if need > 0:
                        args.append(v)
                        need -= 1
            elif n2 in ("push.pri", "push.alt"):
                args.append(self._expr_before(func, j))
                need -= 1
            else:
                break
            j -= 1
        while need > 0:
            args.append("?")
            need -= 1
        return "%s(%s)" % (fname, ", ".join(args))

    def _expr_before(self, func, j):
        """Simple reconstruction of the expression in PRI before push.pri."""
        if j == 0:
            return "?"
        a2, n2, o2 = self.ins[j - 1]
        if n2 in ("load.pri", "load.alt"):
            return self.gname(o2[0])
        if n2 in ("load.s.pri", "load.s.alt", "lref.s.pri"):
            return self.frame_name(func, o2[0], a2)
        if n2 in ("const.pri", "const.alt"):
            return self.const_repr(o2[0])
        if n2 in ("addr.pri", "addr.alt"):
            return self.frame_name(func, o2[0], a2)
        if n2 == "zero.pri":
            return "0"
        if n2 == "load.i":
            return "array[...]"
        if n2 in ("sysreq.c", "call"):
            nm = self.native(o2[0]) if n2 == "sysreq.c" else self.fname(o2[0])
            return nm + "(...)"
        if n2 == "stack" and j >= 2 and self.ins[j - 2][1] in ("sysreq.c", "call"):
            return self._call_repr(func, j - 2, self.native(self.ins[j - 2][2][0])
                                   if self.ins[j - 2][1] == "sysreq.c" else self.fname(self.ins[j - 2][2][0]))
        return "<expr>"

    # ------------- output -------------
    def func_signature(self, k0, k1, faddr):
        name = self.fname(faddr)
        maxarg = -1
        for k in range(k0, k1):
            a, n, ops = self.ins[k]
            if n in FRAME_OPS and ops and ops[0] >= 3 * self.C:
                maxarg = max(maxarg, (ops[0] - 3 * self.C) // self.C)
        # arguments taken from stack/retn (public functions have a fixed count)
        params = [self.frame_name(faddr, 3 * self.C + i * self.C, faddr + self.C) for i in range(maxarg + 1)]
        is_public = any(a == faddr for a, _ in self.a.public_list)
        kw = "public" if is_public else ("main" if name == "main" else "stock")
        return kw, name, params

    def write_pwn(self, out, srcname):
        a = self.a
        w = out.write
        w("// ==========================================================\n")
        w("//  Decompiled from: %s\n" % srcname)
        w("//  amx2pwn  |  cell=%d bit, file v%d, amx v%d, flags=0x%X%s%s\n" % (
            a.cell * 8, a.file_version, a.amx_version, a.flags,
            " COMPACT" if a.flags & AMX_FLAG_COMPACT else "",
            " DEBUG" if a.has_debug else ""))
        if a.shift:
            w("//  Strings decoded with a shift: char = cell >> %d\n" % a.shift)
        w("//  Code: %d B, data: %d B, heap+stack: %d B\n" % (len(a.code), len(a.data), a.stp - a.hea))
        w("//  NOTE: function bodies are Pawn assembly (#emit). Comments\n")
        w("//  show the reconstructed calls and strings.\n")
        w("// ==========================================================\n\n")
        w("#include <a_samp>\n\n" if any(n in a.native_list for n in ("SendClientMessage", "GetPlayerName")) else "")

        if a.library_list:
            w("// --- libraries ---\n")
            for l in a.library_list:
                w("// #pragma library %s\n" % l)
            w("\n")

        w("// --- natives (%d) ---\n" % len(a.native_list))
        for i, n in enumerate(a.native_list):
            w("native %s(...); // #%d\n" % (n, i))
        w("\n")

        if a.tag_list:
            w("// --- tags ---\n")
            for v, n in a.tag_list:
                w("// tag %-24s id=0x%X\n" % (n, v))
            w("\n")

        w("// --- public forwards (%d) ---\n" % len(a.public_list))
        for k0, k1, fa in self.funcs:
            if any(p == fa for p, _ in a.public_list):
                kw, name, params = self.func_signature(k0, k1, fa)
                w("forward %s(%s);\n" % (name, ", ".join(params)))
        w("\n")

        # global variables = data addresses referenced by the code
        refs = set()
        for addr, n, ops in self.ins:
            if n in DATA_OPS or (n in ("push.c", "const.pri", "const.alt") and ops and ops[0] in self.strings):
                if n in DATA_OPS:
                    refs.add(ops[0])
        for addr, _ in a.pubvar_list:
            refs.add(addr)
        arrays = self.arrays
        allg = sorted(r for r in refs | set(arrays) if 0 <= r < len(a.data))
        w("// --- global variables (%d) ---\n" % len(allg))
        str_addrs = sorted(self.strings)
        for idx, g in enumerate(allg):
            nxt = allg[idx + 1] if idx + 1 < len(allg) else len(a.data)
            size = (nxt - g) // self.C
            pub = "public " if g in dict(a.pubvar_list) else ""
            if g in arrays and arrays[g]:
                size = arrays[g]
            base = g // self.C
            hdr = a.data_cells[base:base + size]
            if size > 1 and hdr and hdr[0] == size * self.C and len(hdr) == size:
                diffs = {hdr[i + 1] - hdr[i] + self.C for i in range(size - 1)}
                if len(diffs) == 1:
                    row = diffs.pop() // self.C
                    w("new %s%s[%d][%d];\n" % (pub, self.gname(g), size, row))
                    continue
            if g in arrays and g not in refs and size > 1:
                init = a.data_cells[g // self.C: g // self.C + min(size, 8)]
                if g in self.strings:
                    w("new %s%s[%d] = %s;\n" % (pub, self.gname(g), size, pawn_str(self.strings[g])))
                elif any(init):
                    w("new %s%s[%d]; // init: %s%s\n" % (pub, self.gname(g), size,
                      ", ".join(str(a.sval(x)) for x in init), "..." if size > 8 else ""))
                else:
                    w("new %s%s[%d];\n" % (pub, self.gname(g), size))
            else:
                v = a.sval(a.data_cells[g // self.C])
                w("new %s%s%s;\n" % (pub, self.gname(g), (" = %d" % v) if v else ""))
        w("\n")

        w("// --- string constants (%d) ---\n" % len(self.strings))
        for addr in str_addrs:
            w("// [0x%06X] %s\n" % (addr, pawn_str(self.strings[addr])))
        w("\n")

        # functions
        for k0, k1, fa in self.funcs:
            kw, name, params = self.func_signature(k0, k1, fa)
            calls = self.callers.get(fa, 0)
            w("// ----------------------------------------------------------\n")
            w("// 0x%06X  %s  (called %dx)\n" % (fa, name, calls))
            if kw == "main":
                w("main()\n")
            else:
                w("%s %s(%s)\n" % (kw, name, ", ".join(params)))
            w("{\n")
            for k in range(k0, k1):
                addr, n, ops = self.ins[k]
                if addr in self.labels:
                    w("l_%X:\n" % addr)
                if n == "casetbl":
                    w("    #emit casetbl  // default -> l_%X\n" % ops[1])
                    for t in range(ops[0]):
                        w("    #emit case %d l_%X\n" % (ops[2 + 2 * t], ops[3 + 2 * t]))
                    continue
                if n in JUMPS or n == "switch":
                    opstr = "l_%X" % ops[0]
                elif n == "call":
                    opstr = self.fname(ops[0])
                elif n in ("sysreq.c", "sysreq.n"):
                    opstr = " ".join([self.native(ops[0])] + [str(x) for x in ops[1:]])
                elif n in DATA_OPS:
                    opstr = self.gname(ops[0])
                elif n in FRAME_OPS:
                    opstr = "%d" % ops[0]
                elif n in ("file", "symbol"):
                    opstr = ""
                else:
                    opstr = " ".join(("0x%X" % (x & 0xFFFFFFFF) if abs(x) > 0xFFFF else str(x)) for x in ops)
                line = "    #emit %s %s" % (n, opstr)
                c = self.comment(fa, k)
                if c:
                    line = "%-48s // %s" % (line.rstrip(), c)
                w(line.rstrip() + "\n")
            w("}\n\n")

    def write_asm(self, out):
        a = self.a
        w = out.write
        func_at = {fa for _, _, fa in self.funcs}
        for k, (addr, n, ops) in enumerate(self.ins):
            if addr in func_at:
                w("\n; ===== %s =====\n" % self.fname(addr))
            if addr in self.labels:
                w("l_%X:\n" % addr)
            fa = 0
            w("%08X  %-12s %s" % (addr, n, " ".join(str(x) for x in ops[:12])))
            c = self.comment(fa, k)
            if c:
                w("    ; " + c)
            w("\n")
