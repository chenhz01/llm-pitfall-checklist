#!/usr/bin/env python3
"""self_test battery for llm-pitfall-checklist (functional / errors / edges).

Run:  python self_test.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import llm_pitfall_checklist as lpc  # noqa: E402

HERE = Path(__file__).parent
PY = sys.executable or "python"

DIFF_DEBUG = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,3 +1,5 @@
 def main():
+    print("debug value", x)
+    breakpoint()
     run()
"""

DIFF_TODO = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,4 @@
 def main():
+    # TODO: fix this later
+    run()
"""

DIFF_SCOPE = """diff --git a/random/other.py b/random/other.py
--- a/random/other.py
+++ b/random/other.py
@@ -1,2 +1,3 @@
 def a():
+    b()
"""

DIFF_ABSTRACT = """diff --git a/src/new.py b/src/new.py
new file mode 100644
--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,6 @@
+from abc import ABC, abstractmethod
+
+class BaseHandler(ABC):
+    @abstractmethod
+    def handle(self): ...
"""

DIFF_COMMENT_CODE = """diff --git a/a.js b/a.js
--- a/a.js
+++ b/a.js
@@ -1,2 +1,3 @@
 function f() {
+    // oldInit(config, true);
     return 1;
"""

DIFF_WS_CHURN = """diff --git a/w.txt b/w.txt
--- a/w.txt
+++ b/w.txt
@@ -1,12 +1,12 @@
 line1
 line2
 line3
 line4
 line5
 line6
 line7
 line8
 line9
 line10
 line11
 line12
"""


def _ws_churn_diff():
    lines = [f"line{i}" for i in range(1, 13)]
    old = "\n".join(lines) + "\n"
    new = "\n".join(l + " " for l in lines) + "\n"  # trailing ws everywhere
    hunk = []
    for l in lines:
        hunk.append(f"-{l}")
    for l in lines:
        hunk.append(f"+{l} ")
    return ("diff --git a/w.txt b/w.txt\n--- a/w.txt\n+++ b/w.txt\n"
            f"@@ -1,12 +1,12 @@\n" + "\n".join(hunk) + "\n")


class Functional(unittest.TestCase):
    def test_debug_residue_detected(self):
        v = lpc.lint_diff_text(DIFF_DEBUG)
        rules = {x["rule"] for x in v}
        self.assertIn("LP002", rules)
        self.assertTrue(all(x["severity"] == "error" for x in v if x["rule"] == "LP002"))

    def test_todo_residue_detected(self):
        v = lpc.lint_diff_text(DIFF_TODO)
        self.assertIn("LP003", {x["rule"] for x in v})

    def test_scope_rule_with_allow_glob(self):
        self.assertEqual([x for x in lpc.lint_diff_text(DIFF_SCOPE) if x["rule"] == "LP001"], [])
        v = lpc.lint_diff_text(DIFF_SCOPE, allow_globs=["src/*"])
        self.assertIn("LP001", {x["rule"] for x in v})

    def test_scope_rule_disabled_without_allow(self):
        self.assertEqual(lpc.lint_diff_text(DIFF_SCOPE, allow_globs=None),
                         [])  # plain added line, no other rule trips

    def test_abstraction_smell_detected(self):
        v = lpc.lint_diff_text(DIFF_ABSTRACT)
        lp5 = [x for x in v if x["rule"] == "LP005"]
        self.assertTrue(lp5 and "ABC" in lp5[0]["message"])

    def test_commented_out_code_warn(self):
        v = lpc.lint_diff_text(DIFF_COMMENT_CODE)
        self.assertIn("LP004", {x["rule"] for x in v})
        self.assertEqual(lpc.exit_code_for(v), 0)          # warn only
        self.assertEqual(lpc.exit_code_for(v, strict=True), 1)

    def test_clean_diff_zero_violations(self):
        clean = """diff --git a/src/ok.py b/src/ok.py
--- a/src/ok.py
+++ b/src/ok.py
@@ -1,2 +1,4 @@
 def main():
+    value = compute()
+    return value
"""
        self.assertEqual(lpc.lint_diff_text(clean), [])

    def test_cli_exit_codes_and_json(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "d.txt"
            p.write_text(DIFF_DEBUG, encoding="utf-8")
            r = subprocess.run([PY, str(HERE / "llm_pitfall_checklist.py"), str(p)],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("LP002", r.stdout)
            rj = subprocess.run([PY, str(HERE / "llm_pitfall_checklist.py"), str(p), "--json"],
                                capture_output=True, text=True)
            payload = json.loads(rj.stdout)
            self.assertEqual(payload["summary"]["error"], len(payload["violations"]))
            self.assertGreater(payload["summary"]["error"], 0)


class ErrorPaths(unittest.TestCase):
    def test_empty_input_no_crash(self):
        self.assertEqual(lpc.lint_diff_text(""), [])

    def test_malformed_diff_is_tolerated(self):
        junk = "this is not a diff at all\njust random prose\n"
        self.assertEqual(lpc.lint_diff_text(junk), [])

    def test_hunk_without_file_header_skipped(self):
        orphan = "@@ -1,2 +1,2 @@\n+print(1)\n"
        self.assertEqual(lpc.lint_diff_text(orphan), [])

    def test_missing_diff_file_cli_exit_2(self):
        r = subprocess.run([PY, str(HERE / "llm_pitfall_checklist.py"), "no/such.diff"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_stdin_mode(self):
        r = subprocess.run([PY, str(HERE / "llm_pitfall_checklist.py"), "-"],
                           input=DIFF_DEBUG, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)

    def test_new_file_without_new_marker_still_lints(self):
        noflag = DIFF_ABSTRACT.replace("new file mode 100644\n", "")
        self.assertIn("LP005", {x["rule"] for x in lpc.lint_diff_text(noflag)})


class ExtremeEdges(unittest.TestCase):
    def test_binary_file_line_skipped(self):
        d = ("diff --git a/img.png b/img.png\n"
             "Binary files a/img.png and b/img.png differ\n"
             "+print('this is in the body but must be ignored')\n")
        self.assertEqual(lpc.lint_diff_text(d), [])

    def test_no_newline_marker_tolerated(self):
        d = DIFF_DEBUG + "\\ No newline at end of file\n"
        self.assertIn("LP002", {x["rule"] for x in lpc.lint_diff_text(d)})

    def test_path_with_spaces(self):
        d = ('diff --git a/my file.py b/my file.py\n'
             '--- a/my file.py\n+++ b/my file.py\n'
             '@@ -1,2 +1,3 @@\n x\n+breakpoint()\n')
        v = lpc.lint_diff_text(d)
        self.assertTrue(v and v[0]["file"] == "my file.py")

    def test_whitespace_churn_rule(self):
        v = lpc.lint_diff_text(_ws_churn_diff())
        self.assertIn("LP006", {x["rule"] for x in v})

    def test_crlf_diff(self):
        d = DIFF_DEBUG.replace("\n", "\r\n")
        self.assertIn("LP002", {x["rule"] for x in lpc.lint_diff_text(d)})

    def test_huge_diff_perf(self):
        hunk = ["+value = %d" % i for i in range(20000)]
        d = ("diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n"
             "@@ -0,0 +1,20000 @@\n" + "\n".join(hunk) + "\n")
        t0 = time.perf_counter()
        v = lpc.lint_diff_text(d)
        elapsed = time.perf_counter() - t0
        self.assertEqual(v, [])
        self.assertLess(elapsed, 10.0)
        print(f"\n[perf] 20k-line diff linted in {elapsed:.2f}s (self_test measured)",
              file=sys.stderr)


# ------------------------------------------------------- round-2 additions

class RoundTwo(unittest.TestCase):
    def test_duplicate_block_churn_detected(self):
        body = "\n".join(["+    self.cache[key] = compute_value(key, deep=True)"] * 6)
        d = ("diff --git a/svc.py b/svc.py\n--- a/svc.py\n+++ b/svc.py\n"
             "@@ -1,2 +1,8 @@\n def get(self, key):\n" + body + "\n")
        v = lpc.lint_diff_text(d)
        lp7 = [x for x in v if x["rule"] == "LP007"]
        self.assertTrue(lp7 and "6 times" in lp7[0]["message"])

    def test_duplicate_block_below_threshold_clean(self):
        body = "\n".join(["+    self.cache[key] = compute_value(key, deep=True)"] * 4)
        d = ("diff --git a/svc.py b/svc.py\n--- a/svc.py\n+++ b/svc.py\n"
             "@@ -1,2 +1,6 @@\n def get(self, key):\n" + body + "\n")
        self.assertEqual([x for x in lpc.lint_diff_text(d) if x["rule"] == "LP007"], [])

    def test_short_lines_not_counted_as_dup_block(self):
        body = "\n".join(["+        i += 1"] * 20)  # short lines, ignored
        d = ("diff --git a/loop.py b/loop.py\n--- a/loop.py\n+++ b/loop.py\n"
             "@@ -1,2 +1,22 @@\n def f():\n" + body + "\n")
        self.assertEqual([x for x in lpc.lint_diff_text(d) if x["rule"] == "LP007"], [])

    def test_lp007_is_warning_severity(self):
        body = "\n".join(["+    render_widget(row, col, state=state)"] * 5)
        d = ("diff --git a/ui.py b/ui.py\n--- a/ui.py\n+++ b/ui.py\n"
             "@@ -1,2 +1,7 @@\n def draw():\n" + body + "\n")
        v = lpc.lint_diff_text(d)
        self.assertEqual([x["severity"] for x in v if x["rule"] == "LP007"], ["warn"])
        self.assertEqual(lpc.exit_code_for(v), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
