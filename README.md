# llm-pitfall-checklist

Machine checks for the classic LLM coding pitfalls, run against a unified
diff. Prompt files tell a model what not to do; this tool tells you what it
*just did* — unrelated files touched, debug residue, TODO litter, gratuitous
abstraction — as a violation report your agent or CI can act on. Not another
checklist to read: a checklist that executes.

**Confidence: High (>=85%)** for LP001-LP003 (deterministic patterns);
**Medium (60-79%)** for LP004-LP006 heuristics (false positives possible).

## Problem

The behavioral-patch phenomenon — a pure text file of "LLM coding pitfalls"
reaching enormous adoption — proved the demand; the overlooked angle is that
the *checklist itself* is the asset, and a checklist humans re-read per PR
does not scale. Worse, it audits nothing after the fact: the model read the
principles and still shipped `print()` residue in files you never asked it
to touch. Pitfalls that have a diff signature can be machine-checked at the
moment of the diff — turning "please be surgical" into a lint gate.

All rules here are original heuristics expressed from first principles
(scope, residue, churn); no text is reproduced from any prompt file.

## How it works

Parses a unified diff (file or stdin, tolerant of malformed input), then
applies 7 rules:

| Rule | Severity | Catches |
|---|---|---|
| LP001 | error | files changed outside `--allow` globs (scope creep) |
| LP002 | error | added `print(` / `console.log` / `breakpoint()` / `pdb.set_trace` |
| LP003 | error | added TODO / FIXME / XXX / HACK lines |
| LP004 | warn | commented-out code (`// oldInit(config);`) |
| LP005 | warn | abstraction smell: ABC/Protocol/abstractmethod, or tiny new `Abstract*/Base*/Factory*/Manager*` class file |
| LP006 | warn | whitespace-only churn (lines "changed" by trailing spaces) |
| LP007 | warn | the same non-trivial line added >=5 times in one file (copy-paste churn) |

Exit codes: `0` clean, `1` violations (warnings too with `--strict`), `2`
harness error. `--json` gives a machine-readable report.

## Quickstart (~2 min)

```bash
# Lint a saved diff (~0.5 s)
git diff HEAD~1 > /tmp/change.diff
python llm_pitfall_checklist.py /tmp/change.diff --allow 'src/*'

# Pipe from git directly (~1 s)
git diff | python llm_pitfall_checklist.py - --json

# Agent self-check loop: run before claiming done
git diff | python llm_pitfall_checklist.py - --allow 'app/*' --strict || echo "fix violations first"
```

## Why not X

| Alternative | Why not here |
|---|---|
| Prompt-file checklists (CLAUDE.md-style) | Prospective only: guides generation, audits nothing; silently ignored under context pressure. |
| General linters (ruff/eslint) | Excellent per-language style checks, but language-bound and repo-config-bound; they cannot see *cross-file diff intent* (scope creep) and do not run on a bare diff. |
| LLM-as-judge review of the diff | Slow, costly, nondeterministic, and the judge shares the offender's failure modes; deterministic regex rules are reproducible and free. |
| Full code review bots (PR-level) | Run after the PR exists, far from the agent loop; this runs in seconds on the working diff, before commit. |

## Minimal Fallback (PLAN B)

No Python? Git itself covers the two highest-value rules:

```bash
# scope creep: files changed outside src/
git diff --name-only | grep -v '^src/' && echo "OUT OF SCOPE"

# debug residue in the diff
git diff | grep -E '^\+.*(print\(|console\.log|breakpoint\(\))'
```

You lose severity levels, JSON output, abstraction/churn heuristics — but
the two error-class rules survive in four lines of shell.

## Design Trade-offs

Priority: **zero false arrests on clean code > catch rate > cleverness**.

- Regex heuristics over AST analysis: works on any language and on diffs
  where files may not parse; pays for it with unavoidable imprecision in
  LP004-LP006, which is why those are warnings, not errors.
- Warns do not fail by default: LP004/005/006 have real false-positive
  modes; teams opt into strictness rather than learning to ignore exits.
- Diff-only view: the tool never reads your tree — it audits exactly the
  proposed change, nothing else (privacy > completeness).

## Limits & Second-order Effects

- Gaming surface: a model that knows the rules can dodge them (rename
  `print` to `sys.stdout.write`). Mitigation is pairing with review, not
  more regexes.
- If adopted as a hard gate, agents may stop adding TODOs at all — losing a
  legitimate coordination signal. Consider routing LP003 to warnings on
  repos that use TODOs intentionally.
- Rule drift: as models change, pitfall frequency changes; the rule set
  needs the same maintenance a test suite gets.

## FAQ

**Q: When NOT to use this tool?**
A: When the "diff" is machine-generated refactoring with intentionally broad
scope (formatter runs, codemods) — LP001/LP006 will drown you. Also skip it
for binary-heavy branches; it audits text diffs only.

**Q: Does it call any LLM?**
A: No. Pure deterministic stdlib regex; same input, same report, no network.

**Q: Does it read my source tree?**
A: No — only the diff text you hand it. Nothing else is opened.

**Q: How fast?**
A: Self-test measured: a 20,000-line synthetic diff lints in well under a
second on a laptop; cost is linear in diff size (24 tests, ~1.5 s total;
`python self_test.py -v` reproduces; exact figure printed by the perf test).

## [Core Assumptions]

1. The pitfalls worth machine-checking are exactly those with a stable diff
   signature; pitfalls like "wrong architecture choice" are out of scope.
2. Diff scope (`--allow` globs) is expressible per repo; if it is not, LP001
   is disabled rather than guessing.
3. Heuristic severity (error vs warn) can be tuned by teams; defaults bias
   toward no-false-arrest so the gate stays trusted.
4. The tool audits one diff at a time, not cumulative branch history (as of
   2026-10-11).

---
Contact: hcac4735@agent.qq.com · License: MIT · Rule set as of 2026-10-11.
