# amx2pwn

An experimental decompiler that turns compiled Pawn scripts (`.amx`) back into
readable `.pwn` source that compiles again. It targets SA-MP / open.mp gamemodes
and filterscripts.

> **About this project**
>
> amx2pwn is an experiment, not a maintained product. It was built to test how
> far an AI coding assistant can get with a niche reverse-engineering task:
> reading a bytecode format, rebuilding control flow and producing code a human
> can edit. Almost all of the code was written by Claude (Anthropic). A human
> supplied the test scripts, ran the checks and steered the work.
>
> Pawn and SA-MP are mostly history by now. The scripts it was tested on date
> from around 2008–2013. Expect rough edges, and only decompile scripts you
> have the right to work with.

## Example

[`examples/welcome.pwn`](examples/welcome.pwn) was compiled without debug
info, so the `.amx` contains no variable or function names. The decompiler
gives back:

```pawn
new g_0[50];

stock func_8()
{
    new var0;
    for (new i; i < 50; i++)
    {
        if (IsPlayerConnected(i))
        {
            var0++;
        }
    }
    return var0;
}

public OnPlayerConnect(playerid)
{
    new name[24];
    new string[128];
    GetPlayerName(playerid, name, sizeof(name));
    g_0[playerid]++;
    format(string, sizeof(string), "Welcome, %s! Players online: %d", name, func_8());
    SendClientMessage(playerid, 0x33CCFFFF, string);
    if (g_0[playerid] > 1)
    {
        SendClientMessage(playerid, -1, "Welcome back!");
    }
    return 1;
}
```

The full output is in
[`examples/welcome.decompiled.pwn`](examples/welcome.decompiled.pwn). Names
like `playerid`, `name` and `string` are inferred from how the values are used.
Names the decompiler can't infer get placeholders such as `g_0` or `func_8`.

## Usage

Requires Python 3.8+ and nothing else.

```bash
python -m amx2pwn gamemode.amx
```

This writes `gamemode.pwn` (the decompiled source) and `gamemode.asm` (a
disassembly listing). It refuses to overwrite an existing `.pwn` that it did not
write itself.

| Option | Meaning |
|---|---|
| `-o out.pwn` | output file (single input only) |
| `--no-asm` | skip the `.asm` listing |
| `--emit` | don't decompile; print function bodies as `#emit` assembly |
| `--utf8` | convert strings from cp1250 to UTF-8 (default: bytes kept 1:1) |
| `--shift N` | force string decoding as `char = cell >> N` (default: auto-detect) |
| `--force` | overwrite an existing `.pwn` |

You can also install it as a command with `pip install .` and then run
`amx2pwn gamemode.amx`.

The output declares all natives and float operators itself, so it compiles
with `pawncc` without `a_samp.inc` or `float.inc`.

## What it handles

- **File format:** 16/32/64-bit cells, compact encoding, file versions 1–11,
  old and new name tables, and debug info (`-d1`..`-d3`), which gives real names.
- **Control flow:** `if` / `else if` / `else`, `while`, `do … while`, `for`,
  `switch`, `break` / `continue`, `&&` / `||` chains, `?:`, and assignments
  inside conditions.
- **Data:**
  - local and global variables, plus 1D, 2D, ragged 2D (`new names[][] = {…}`) and 3D arrays with their initial values;
  - parameters passed by value, by reference and as arrays, including `arg[][]`;
  - variadic functions (`func(a, ...)`);
  - functions that return strings;
  - packed and unpacked strings.
- **Floats:** `Float:` tags are inferred for variables, arrays, parameters and
  return values. `floatadd(a, b)` becomes `a + b`, and `floatcmp(a, b) > 0`
  becomes `a > b`.
- **Readability:**
  - well-known library functions are recognised and named (dini, dudb, dutils, `strtok`, `IsNumeric`, …), and so are `dcmd_*` commands;
  - variable names are inferred from usage (`x, y, z`, `name`, `len`, loop counters `i, j, k`);
  - natives get proper argument forms: `sizeof(array)`, `true` / `false`, `'a'` / `EOS`, enum constants like `io_read`, and trailing default arguments are dropped;
  - old-compiler quirks are reproduced so the output compiles with a current `pawncc`.

## How well does it work?

It was tested on 17 real SA-MP scripts, about 2,000 functions in total, ranging
from tiny filterscripts to 300-function gamemodes:

- Every output compiles with `pawncc` 3.10.10 with **0 errors**. Warnings
  remain, mostly about unused variables and parameters that were in the
  original code.
- **Round trip:** each output was compiled again, decompiled again and
  compared with the first output. About 99% of functions come back with the
  same structure. In the rest, the operands of a comparison are swapped, the
  branches of a `?:` are in the other order, or a temporary variable is left
  over. None of the differences we checked changed behaviour.
- Even the largest script takes under 3 seconds to decompile.

What it does **not** do:

- **Comments, macros, `#define`s, `enum` names** and **original names** can't
  come back without debug info, because the compiler throws them away.
- **`goto` and odd control flow:** code the compiler produced from `goto` or
  unusual jumps can come out as `goto` / labels or as `#emit` blocks.
- **Unusual compiler or plugin tricks** may fail. A function that can't be
  decompiled is written as a comment that points to the `.asm` listing, and
  the rest of the file is still produced.

## Code layout

```
amx2pwn/
  amxfile.py      .amx parser: header, tables, code/data, debug info, strings
  opcodes.py      Pawn opcode table
  listing.py      disassembler (.asm listing and --emit output)
  decompiler.py   bytecode simulation -> expression tree -> structured statements
  nodes.py        expression / statement tree and its helpers
  render/         turns the tree into Pawn source (one mixin per concern)
    floats.py       Float: tag inference
    readability.py  library recognition, naming, default arguments
    layout.py       layout of global arrays (1D/2D/3D/ragged)
    expressions.py  expression output
    statements.py   statement output
    output.py       whole-file output, declarations, naming passes
  natives.py      loads the native tables; Pawn core natives with default arguments
  omp_natives.py  SA-MP / open.mp natives and callbacks (generated, MPL-2.0)
  libraries.py    signatures of well-known library functions, naming tables
  literals.py     formatting of strings, floats and numbers
  cli.py          command line interface
tools/
  gen_natives.py  regenerates omp_natives.py from the open.mp includes
```

### Adding a library

Many scripts bundled the same include files. To teach the decompiler a new
function, add a line to `LIBSIGS` in
[`amx2pwn/libraries.py`](amx2pwn/libraries.py). Each entry gives the function's
name, its parameter names, and the features that identify its compiled code:
number of parameters, natives it calls, string literals, constants and so on.
For example:

```python
("IsNumeric", ["string"], dict(nat=["strlen"], np=1, ret_arr=False,
                               natonly=["strlen"], const=[48, 57], nocalls=True)),
```

## Tests

```bash
python -m unittest discover tests
```

The test decompiles the bundled example and compares the result with the
expected output. The broader checks described above (compiling and
round-tripping real scripts) need `pawncc` and the scripts themselves, so they
aren't part of the repository.

## Credits

- The SA-MP / open.mp native and callback signatures in
  [`amx2pwn/omp_natives.py`](amx2pwn/omp_natives.py) are generated from the
  [open.mp Pawn includes](https://github.com/openmultiplayer/omp-stdlib) by
  [`tools/gen_natives.py`](tools/gen_natives.py). That file is derived from
  open.mp and is licensed under the
  [Mozilla Public License 2.0](https://mozilla.org/MPL/2.0/).
  The rest of amx2pwn does not depend on it being MPL.
- [DeAMX](https://github.com/AmyrAhmady/DeAMX) by trc_ (2008, updated by
  iAmir in 2018), an earlier AMX decompiler, was an inspiration. No code or
  data from it is included.
- Pawn and the AMX format are by ITB CompuPhase. The tool was tested with the
  community [pawn compiler](https://github.com/pawn-lang/compiler).
