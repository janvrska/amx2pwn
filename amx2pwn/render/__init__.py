"""Renderer: turns decompiled functions into readable, compilable Pawn."""

from .floats import FloatsMixin
from .readability import ReadabilityMixin
from .layout import LayoutMixin
from .expressions import ExpressionsMixin
from .statements import StatementsMixin
from .output import OutputMixin


class Renderer(FloatsMixin, ReadabilityMixin, LayoutMixin, ExpressionsMixin, StatementsMixin, OutputMixin):
    """Turns the decompiled functions into a Pawn source file."""

    def __init__(self, d):
        self.d = d
        self.C = d.C
        self.marks_changed = False
        self.F = set()
        self.locs = {}
        self.float_ret = set()
        self.ops_used = set()
        self.layout_ready = False
