#!/usr/bin/env python3
"""llm-pitfall-checklist: diff-level machine checks for LLM coding pitfalls.

Static-LLM prompt files tell a model what NOT to do; they cannot tell you
what it *just did*. This tool runs the pitfall checklist against a unified
diff and emits a violation report:

  LP001 out-of-scope-file      files changed outside --allow globs
  LP002 debug-residue          print/console.log/breakpoint/pdb added
  LP003 todo-residue           TODO/FIXME/XXX/HACK lines added
  LP004 commented-out-code     code pasted under a comment marker
  LP005 abstraction-smell      ABC/Protocol/abstractmethod or tiny
                               Abstract*/Base*/Factory*/Manager* class file
  LP006 whitespace-churn       lines "changed" only by trailing whitespace
  LP007 duplicate-block-churn  the same non-trivial line added >=5 times
                               in one file (copy-paste / loop unrolling)

Severity: LP001-LP003 error, LP004-LP006 warn. Exit 1 on any error, or on
warnings with --strict. Exit 2 on harness errors.

Usage: llm_pitfall_checklist.py diff.txt [--allow 'src/*'] [--json] [--strict]
       cat diff.txt | llm_pitfall_checklist.py -
Pure standard library. Rules are original heuristics, not copied text.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

MAX_FILE_BYTES = 20 * 1024 * 1024

# Patterns match the *content* of an added line (the leading '+' is stripped
# by the parser before matching).
DEBUG_RE = re.compile(
    r"^\s*(print\s*\(|console\.(log|debug|info)\(|breakpoint\(\)|"
    r"pdb\.set_trace\(\)|System\.out\.print)",
)
TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
COMMENT_CODE_RE = re.compile(
    r"^\s*(#|//)\s*\S.*(=|;|\breturn\b|\bimport\b|<<|\(\))")
ABSTRACT_RE = re.compile(
    r"\b(abc\.ABC|\(ABC\)|Protocol\)|@abstractmethod)\b")
SMELL_CLASS_RE = re.compile(r"^\s*class\s+\w*(Abstract|Base|Factory|Manager|Impl)\w*[\(:]")

ERROR_RULES = {"LP001", "LP002", "LP003"}


class DiffFile:
    __slots__ = ("path", "is_new", "added", "removed", "binary")

    def __init__(self, path, is_new=False):
        self.path = path
        self.is_new = is_new
        self.added = []    # (line_no, text)
        self.removed = []  # text
        self.binary = False


def parse_unified_diff(text: str):
    """Extract per-file added/removed lines. Tolerates malformed input by
    skipping to the next file header."""
    files = []
    cur = None
    new_path = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            if cur is not None:
                files.append(cur)
            m = re.search(r" b/(.+)$", line)
            new_path = m.group(1) if m else None
            cur = DiffFile(new_path or "?")
        elif line.startswith("Binary files") or line.startswith("GIT binary patch"):
            if cur is not None:
                cur.binary = True
        elif line.startswith("+++ "):
            m = re.match(r"^\+\+\+ (?:b/)?(.+?)(?:\t|$)", line)
            if m and m.group(1) != "/dev/null":
                target = m.group(1)
                if cur is None or cur.path != target:
                    if cur is not None:
                        files.append(cur)
                    cur = DiffFile(target)
                elif cur.path == "?":
                    cur.path = target
        elif line.startswith("--- "):
            continue
        elif line.startswith("@@"):
            continue
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        elif cur is not None and not cur.binary:
            if line.startswith("+") and not line.startswith("+++"):
                cur.added.append((len(cur.added) + 1, line[1:]))
            elif line.startswith("-") and not line.startswith("---"):
                cur.removed.append(line[1:])
    if cur is not None:
        files.append(cur)
    for f in files:
        if f.path == "?":
            f.binary = True  # unidentifiable target: skip content rules
    return files


def _lint_file(f: DiffFile, allow_globs):
    v = []
    if f.binary:
        return v

    # LP001 scope
    if allow_globs:
        hit = any(fnmatch.fnmatch(f.path, g) for g in allow_globs)
        if not hit:
            v.append({"rule": "LP001", "severity": "error", "file": f.path,
                      "line": 0,
                      "message": f"file outside allowed scope {allow_globs}"})

    removed_stripped = {}
    for r in f.removed:
        removed_stripped[r.rstrip()] = removed_stripped.get(r.rstrip(), 0) + 1

    ws_churn = 0
    smell_class_lines = 0
    for no, text in f.added:
        if DEBUG_RE.match(text):
            v.append({"rule": "LP002", "severity": "error", "file": f.path,
                      "line": no, "message": f"debug residue added: {text.strip()[:60]}"})
        if TODO_RE.search(text):
            v.append({"rule": "LP003", "severity": "error", "file": f.path,
                      "line": no, "message": f"TODO/FIXME residue added: {text.strip()[:60]}"})
        if COMMENT_CODE_RE.match(text):
            v.append({"rule": "LP004", "severity": "warn", "file": f.path,
                      "line": no, "message": f"commented-out code added: {text.strip()[:60]}"})
        if ABSTRACT_RE.match(text) or SMELL_CLASS_RE.match(text):
            smell_class_lines += 1
        # whitespace-only churn: same content as a removed line modulo trailing ws
        if text != text.rstrip() and removed_stripped.get(text.rstrip(), 0) > 0:
            ws_churn += 1

    # LP005 abstraction smell
    if ABSTRACT_RE.search("".join(t for _, t in f.added)) or smell_class_lines:
        tiny = f.is_new and len([t for _, t in f.added if t.strip()]) < 25
        if smell_class_lines or tiny:
            v.append({"rule": "LP005", "severity": "warn", "file": f.path,
                      "line": 0,
                      "message": "abstraction smell: "
                                 + ("new tiny Abstract*/Base*/Factory*/Manager* file"
                                    if tiny else "ABC/Protocol/abstractmethod introduced")})
    # LP006 whitespace churn
    if ws_churn >= 10 and ws_churn >= max(3, len(f.added) // 4):
        v.append({"rule": "LP006", "severity": "warn", "file": f.path,
                  "line": 0,
                  "message": f"{ws_churn} whitespace-only line changes (trailing-ws churn)"})
    # LP007 duplicate-block churn: identical non-trivial added lines
    added_counter = {}
    for _, t in f.added:
        if len(t.strip()) >= 12:  # ignore short/blank lines
            added_counter[t] = added_counter.get(t, 0) + 1
    dup = max(added_counter.values()) if added_counter else 0
    if dup >= 5:
        v.append({"rule": "LP007", "severity": "warn", "file": f.path,
                  "line": 0,
                  "message": f"same line added {dup} times (copy-paste churn)"})
    return v


def lint_diff_text(text: str, allow_globs=None) -> list:
    files = parse_unified_diff(text)
    violations = []
    for f in files:
        violations.extend(_lint_file(f, allow_globs))
    return violations


def exit_code_for(violations, strict=False) -> int:
    if any(v["severity"] == "error" for v in violations):
        return 1
    if strict and violations:
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="llm-pitfall-checklist",
        description="Diff-level machine checks for LLM coding pitfalls "
                    "(unrelated files, debug residue, over-abstraction, ...).")
    ap.add_argument("diff", help="path to unified diff, or '-' for stdin")
    ap.add_argument("--allow", action="append", default=[],
                    help="glob of in-scope file paths (repeatable); "
                         "LP001 disabled when unset")
    ap.add_argument("--strict", action="store_true", help="warnings also fail")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.diff == "-":
        text = sys.stdin.read()
    else:
        p = Path(args.diff)
        if not p.is_file():
            print(f"error: diff file not found: {p}", file=sys.stderr)
            return 2
        if p.stat().st_size > MAX_FILE_BYTES:
            print(f"error: diff exceeds {MAX_FILE_BYTES} bytes", file=sys.stderr)
            return 2
        text = p.read_text(encoding="utf-8", errors="replace")

    violations = lint_diff_text(text, allow_globs=args.allow or None)
    if args.json:
        print(json.dumps({"violations": violations,
                          "summary": {
                              "total": len(violations),
                              "error": sum(1 for v in violations if v["severity"] == "error"),
                              "warn": sum(1 for v in violations if v["severity"] == "warn")}},
                         indent=2))
    else:
        if not violations:
            print("llm-pitfall-checklist: no violations")
        for v in violations:
            print(f"{v['rule']} [{v['severity']}] {v['file']}:{v['line']} {v['message']}")
    return exit_code_for(violations, strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
