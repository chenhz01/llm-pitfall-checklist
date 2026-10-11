# Changelog — llm-pitfall-checklist

## v0.1.1 — 2026-10-11 (round-2 iteration: rule coverage)

### Added
- **LP007 duplicate-block churn**: the same non-trivial line (>=12 chars)
  added >=5 times in one file flags copy-paste churn / unrolled loops
  (warn severity). Short and blank lines are ignored to protect legitimate
  loop bodies.
- Round-2 tests: LP007 detection, below-threshold clean case, short-line
  exclusion, severity/exit-code semantics. Test count 20 → 24 (+20%).

### Changed
- README: rule table extended to 7 rules; perf FAQ re-measured (24 tests
  in ~1.5 s).

## v0.1.0 — 2026-10-11

Initial draft: unified-diff parser tolerant of malformed input (orphan
hunks, binary lines, CRLF, no-newline markers, paths with spaces), 6 rules
(LP001 scope creep via --allow globs, LP002 debug residue, LP003 TODO
residue, LP004 commented-out code, LP005 abstraction smell, LP006
whitespace churn), severity model, `--json`, stdin mode, exit codes
0/1/2, 20-test battery including a 20k-line perf smoke.
