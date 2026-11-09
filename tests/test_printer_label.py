"""v3.0.9 REGRESSION: the extension Default-printer dropdown duplicated
every printer name ("HP Laser 103 107 108HP Laser 103 107 108").

Root cause: the option label in loadPrinters() was written as

    p.name + (ternary..., p.name)

- one closing paren short. Inside the parens the comma parsed as the
COMMA OPERATOR, so the whole parenthesized expression evaluated to the
second operand (p.name) and the label became p.name + p.name while the
[status] / (OS default) decorations were silently discarded.

The fix closes the paren. This test replays the EXACT expression from
extension/options.js (both the old broken and the fixed form) with
Node.js and asserts the fixed label contains the name exactly once
with the decorations restored. Skips cleanly when node is missing."""
import os
import re
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)          # repo root (HERE = tests/)
OPTIONS_JS = os.path.join(ROOT, "extension", "options.js")

NODE = shutil.which("node")

# the broken v3.0.8 expression (verbatim) - kept here as the regression
# oracle: whatever the fix, THIS shape must never come back
BROKEN = """
const p = {name: NAME, is_group: false, status: "ready", is_default: true};
const label = p.name + (p.is_group ? "  (group)"
        : (p.status && p.status !== "unknown"
           ? "  [" + p.status + "]" : "") +
        (p.is_default ? "  (OS default)" : ""), p.name);
console.log(JSON.stringify(label));
"""

FIXED = """
const p = {name: NAME, is_group: false, status: "ready", is_default: true};
const label = p.name + (p.is_group ? "  (group)"
        : ((p.status && p.status !== "unknown"
           ? "  [" + p.status + "]" : "") +
        (p.is_default ? "  (OS default)" : "")));
console.log(JSON.stringify(label));
"""


def _run(js, name="OneNote (Desktop)"):
    src = js.replace("NAME", repr(name))
    out = subprocess.run([NODE, "-e", src], capture_output=True,
                         text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip().strip('"')


def _fixed_expression_from_source():
    """Pull the live label expression out of options.js so the test
    fails if the source ever drifts from the fixed shape."""
    src = open(OPTIONS_JS, encoding="utf-8").read()
    m = re.search(r"new Option\(\s*(p\.name \+\ \(.*?)\s*,\s*p\.name\s*\)",
                  src, re.S)
    assert m, "options.js loadPrinters label expression not found"
    return m.group(1)


@pytest.mark.skipif(NODE is None, reason="node.js not installed")
def test_broken_shape_reproduces_the_doubled_name():
    assert _run(BROKEN) == "OneNote (Desktop)OneNote (Desktop)"


@pytest.mark.skipif(NODE is None, reason="node.js not installed")
def test_fixed_shape_renders_once_with_decorations():
    out = _run(FIXED)
    assert out == "OneNote (Desktop)  [ready]  (OS default)"
    assert out.count("OneNote (Desktop)") == 1


@pytest.mark.skipif(NODE is None, reason="node.js not installed")
def test_options_js_expression_is_the_fixed_one():
    expr = _fixed_expression_from_source()
    src = ("const p = {name: %r, is_group: false, status: 'ready', "
           "is_default: true};\n"
           "const label = %s;\n"
           "console.log(JSON.stringify(label));" % ("HP Laser 103 107 108",
                                                    expr))
    out = subprocess.run([NODE, "-e", src], capture_output=True,
                         text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    label = out.stdout.strip().strip('"')
    assert label == "HP Laser 103 107 108  [ready]  (OS default)"
    assert label.count("HP Laser 103 107 108") == 1
