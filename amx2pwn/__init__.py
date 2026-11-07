"""amx2pwn - decompiler for compiled Pawn (.amx) scripts, aimed at SA-MP / open.mp.

Turns an .amx file back into an editable .pwn file that compiles with pawncc.

    from amx2pwn import decompile_file
    decompile_file("gamemode.amx")          # writes gamemode.pwn + gamemode.asm
"""

from .cli import process as decompile_file

__all__ = ["decompile_file"]
__version__ = "1.0.0"
