# Comparison with other AMX decompilers

Two other open-source decompilers target SA-MP / open.mp `.amx` files:
[PyDeAMX](https://github.com/najuaircrack/PyDeAMX) and
[DeAMX](https://github.com/AmyrAhmady/DeAMX). They take different approaches,
so the right one depends on what you need. The table is based on each
project's code and documentation as of November 2026.

| | amx2pwn | PyDeAMX | DeAMX |
|---|---|---|---|
| **Runtime** | Python 3.8+, no dependencies | Python 3.10+, no dependencies (Tkinter for the GUI) | Lua 5.1 |
| **Interface** | command line | command line and desktop GUI | command line |
| **History** | 2026 | 2026, Python rewrite carrying DeAMX's name and license | 2008 (trc_), updated 2018, last commit 2021 |
| **Cell size** | 16, 32 and 64-bit | 32-bit | 32-bit |
| **AMX file versions** | 1–11, old and new name tables | 6–11, new name table | new name table, version not checked |
| **Debug info** | names | names, tags, scopes, array dimensions | not read |
| **Main goal** | readable source for a person to edit | a rebuild that can be shown to behave like the original | readable source |
| **Output** | one self-contained `.pwn` that declares its own natives, plus `.asm` | `.pwn` with `#include`s, a companion `.runtime.inc`, a JSON report and `.asm` | `.pwn` with `#include <a_samp>` |
| **Needs** | only the `.amx` | the `.amx` and a matching include tree (`-I`) | only the `.amx` |
| **Control flow** | `if` / `else if` / `else`, `while`, `do … while`, `for`, `switch`, `break` / `continue`, `&&` / `\|\|`, `?:` | branches, `switch`, loops as `while` / `for (;;)`; leftover jumps stay as labels; functions it can't lift are emitted as Pawn code that emulates the original instructions | `if` / `else`, `while`, `for`, `switch`, `?:` |
| **Floats** | `Float:` tags inferred, `floatadd(a, b)` turned back into `a + b` | tags from debug info and include signatures | tags from native and callback prototypes |
| **Names without debug info** | inferred from usage (`playerid`, `name`, `i`, …) | inferred from usage | from native and callback prototypes |
| **Libraries** | well-known library functions (dini, dudb, `strtok`, …) recognised and named; their code stays in the output | functions from include trees (`-I`) checked against a compiler and replaced by an `#include` | planned |
| **Checking the result** | not built in; compile the output with `pawncc` yourself | optional `--compiler` step recompiles and checks data, publics and offsets; its tests run original and rebuilt AMX side by side in a VM | not built in |
| **Anti-decompiler tricks** | handled where the code is still valid | unusual constructs kept as explicit VM operations or marked with `#error` | bypasses the known anti-DeAMX methods |
| **Testing** | 332 real scripts from 2008–2013 (private archive), round trip on 17 | 23 tests on public fixtures, CI on Windows and Linux | no tests |
| **License** | MPL-2.0 for the generated native table; rest not stated | historical DeAMX license (no selling, not OSI-approved) | own license (free use and modification, no selling) |

The test results are not directly comparable: amx2pwn reports how many real
scripts compile again, PyDeAMX checks behaviour on small purpose-built
fixtures.

## On the same scripts

All three tools were run on six SA-MP gamemodes from around 2008–2010
(32-bit, file version 8, no debug info, 300–670 KB). Each output was then
compiled with `pawncc` 3.10.10 and the SA-MP 0.3.7 includes (amx2pwn's
output needs no includes).

| | amx2pwn | PyDeAMX | DeAMX |
|---|---|---|---|
| **Finished** | 6 of 6 | 6 of 6 | 5 of 6 (crashed on one while writing global arrays) |
| **Output compiles** | 6 of 6 with 0 errors; 31–478 warnings, mostly tag mismatches and unused symbols | 0 of 6, also in its own `--compiler` check: undefined or duplicate generated helpers (12 to 26+ errors) | 0 of 5: invalid array syntax stops the compiler early (5–10+ errors) |
| **Functions as readable Pawn** | all | 59% (26–87% per script); the rest emulate the original instructions | all, in the scripts it finished |
| **Size of output** | one `.pwn`, 9–19k lines | `.pwn` of 6–31k lines plus a `.runtime.inc` of 76–230k lines | one `.pwn`, 9–18k lines |
| **Time per script** | 1–2 s | 1.5–15 s | 1–2 s |

In the functions all three lift, amx2pwn and DeAMX produce similar code.
amx2pwn names more variables and adds more `Float:` tags. DeAMX
resolved some string arguments that amx2pwn left as raw addresses. PyDeAMX's
readable functions keep every intermediate value, so they are longer: one
geometry function is 64 lines in amx2pwn and 593 in PyDeAMX.

## Which one fits

- **amx2pwn** fits older scripts (old compilers, old name tables, 16- or
  64-bit cells) and cases where you want a single `.pwn` that reads like
  hand-written code and compiles without the original includes.
- **PyDeAMX** fits when you have the exact include versions and a `pawncc`,
  and want the tool to check that the rebuilt script matches the original.
  It keeps libraries as `#include`s instead of copying their code, and has a
  GUI.
- **DeAMX** is the original tool that the other two build on in spirit. Its
  small Lua code base is easy to study, and it works for a quick look at
  32-bit SA-MP 0.3.x scripts if you have Lua at hand.
