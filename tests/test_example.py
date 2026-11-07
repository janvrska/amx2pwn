"""Regression test: decompiling examples/welcome.amx must give examples/welcome.decompiled.pwn.

Run with:  python -m unittest discover tests
"""

import os
import tempfile
import unittest

from amx2pwn import decompile_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = os.path.join(ROOT, "examples")


class ExampleTest(unittest.TestCase):
    def test_welcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "welcome.decompiled.pwn")
            decompile_file(os.path.join(EXAMPLES, "welcome.amx"), out, asm=False)
            with open(out, encoding="latin-1") as f:
                got = f.read()
        with open(os.path.join(EXAMPLES, "welcome.decompiled.pwn"), encoding="latin-1") as f:
            expected = f.read()
        self.assertEqual(got, expected)

    def test_refuses_to_overwrite_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "welcome.pwn")
            with open(src, "w") as f:
                f.write("// hand-written source\n")
            with open(os.path.join(EXAMPLES, "welcome.amx"), "rb") as f:
                data = f.read()
            amx = os.path.join(tmp, "welcome.amx")
            with open(amx, "wb") as f:
                f.write(data)
            with self.assertRaises(Exception):
                decompile_file(amx, asm=False)
            with open(src) as f:
                self.assertEqual(f.read(), "// hand-written source\n")


if __name__ == "__main__":
    unittest.main()
