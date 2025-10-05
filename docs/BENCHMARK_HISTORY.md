# Benchmark History and Change Log

This doc tracks benchmark runs, average grades, and major retrieval/LLM changes across versions. All changes are generalizable (no per‑question curve fitting).

## Summary Table

| Version | Date (approx) | Mini LLM | Grader | Avg Grade | Notes |
|--------:|----------------|----------|--------|-----------|-------|
| v2 | earlier | off | heuristic | 1.30 | Content‑first added; baseline still low |
| v3 | earlier | off | heuristic | 1.90 | Priority 1 fixes; definition boost; +top_files |
| v4 | recent | off | heuristic | 2.00 | focus_read peeks integrated; include breadth; repo cleanup |
| v5 | recent | on | heuristic | 1.80 | Mini rescoring added (but temp=0 caused 400s intermittently) |
| v6 | recent | off | heuristic | 1.20 | Rule‑based only; verified .env loading; peeks/extractors in place |
| v7 | recent | off | heuristic | 1.00 | Early exit artifact (fixed later) |
| v8 | recent | off | heuristic | 1.00 | Model mismatch; used for validation only |
| v9 | recent | off | heuristic | 1.30 | Stable baseline with peeks/extractors visible |
| v10 | recent | on | heuristic | 2.00 | Mini ON; improved Q1/Q7/Q8; slower latency |
| v11 | recent | on | LLM | 2.30 | Mini ON + LLM grading (reasoned); console debug enabled |
| v12 | recent | on | LLM | 3.00 | Filename channel + authority tweaks + follow‑up best‑of |
| v13 | recent | on | LLM | 2.40 | Nested/symbol groundwork; repo evidence variance |
| v14 | recent | on | LLM | 2.40 | Nested .msg (depth 2), cross‑file symbol capture |

Notes: “Mini LLM” refers to enabling classification/judge/rescoring with `OPENAI_MINI_MODEL` (FOCUS_USE_MINI=1). “Grader” indicates whether scores were produced heuristically or by the mini LLM with reasoning (`--llm-grade`).

## Version Details

### v2 (avg 1.30)
- Major changes:
  - Content‑first mode in `focus_probe` to search entire base and cluster after.
  - Classifier prompt emphasized content_first for most queries.
- Outcomes:
  - Baseline precision still low. Definition documents present but ranking favored mentions over definitions.
- Issues:
  - No filename channel; authority files (.msg/.urdf) often missed.

### v3 (avg 1.90)
- Major changes:
  - Definition boost (readme-in-keyword-dir, H1/title, “stands for”).
  - Increased `top_files` shown to LLM.
- Outcomes:
  - Q1 (acronym) improved strongly set‑wide; others partial.
- Issues:
  - Messages/joints still constrained by discovery (lack of authority targeting).

### v4 (avg 2.00)
- Major changes:
  - Integrated `focus_read` into probe peeks (bounded head/tail; binary‑safe).
  - Broadened default include globs in `focus_grep` (ROS/robot/doc types).
  - Repo cleanup (docs/, scripts/, results/).
- Outcomes:
  - More stable peeks; better context for definitions/docs.

### v5 (avg 1.80)
- Major changes:
  - Mini‑LLM rescoring added (heads), but set `temperature=0.0` caused 400 errors for some mini models.
- Outcomes:
  - Mixed improvements; occasional rescoring ineffectiveness; added latency.

### v6 (avg 1.20)
- Major changes:
  - Verified `.env` loading via python‑dotenv; mini disabled for baseline.
  - Extractors in probe (msg/urdf) and larger peeks configured.
- Outcomes:
  - Low average confirms need for LLM classification/rescoring.

### v7 (avg 1.00)
- Notes: Early exit path in one run; later corrected.

### v8 (avg 1.00)
- Notes: Model slug mismatch run; kept for completeness.

### v9 (avg 1.30)
- Major changes:
  - Mini OFF with verbose+debug; baseline consistency.
- Outcomes:
  - Slight improvement over v6.

### v10 (avg 2.00)
- Major changes:
  - Mini ON for classify/judge/rescore; `--llm-verbose`.
- Outcomes:
  - Clear wins on definitions/docs; slower runtime.

### v11 (avg 2.30, LLM grading)
- Major changes:
  - Enabled `--llm-grade`: mini LLM grades each answer and returns reasons.
  - Fixed mini rescore temperature (omit param when unsupported).
- Outcomes:
  - Better measurement (reasons for partial credit);
  - Improved average vs v10.

### v12 (avg 3.00, LLM grading)
- Major changes:
  - Filename channel wired through plans: `file_name_globs` + `--include-all` (e.g., robot_actions.py, pyproject.toml, Dockerfile*).
  - Authority weighting tweaks (boost authority dirs; slight README bonus; demote legacy/examples/tests).
  - Follow‑up best‑of safeguard to avoid regressions.
- Outcomes:
  - Big improvements: Q2 (3/5), Q3 (4/5), Q5 (5/5), Q9 (5/5).

### v13 (avg 2.40, LLM grading)
- Major changes:
  - Nested/symbol groundwork and plumbing.
- Outcomes:
  - Stable but slightly lower average vs v12; evidence variance across repo questions.

### v14 (avg 2.40, LLM grading)
- Major changes:
  - Nested .msg extraction up to depth 2 with bounded breadth.
  - Cross‑file Python symbol capture when symbol not in top files.
- Outcomes:
  - Q1 remained high; Q9 retained 5/5; mixed impact on others due to missing authority files or conflicting repo ground truth.

## Current System Capabilities (at v14)
- `focus_probe`:
  - Content‑first or directory‑first discovery; include breadth via `--include-all`.
  - Filename channel: `--file-name-regex/--file-name-globs/--filename-weight` to promote canonical files.
  - Authority weighting for `.msg/.idl/.srv/.urdf/.xacro`, and authority dirs.
  - Peeks (head=400, tail=80) via `focus_read`.
  - Extractors:
    - `extracted_msg_fields` (top–level), `extracted_msg_nested` (depth 2),
    - `extracted_urdf_joints` (from URDF/XACRO),
    - `extracted_symbol` (function block), and bundle‑level `symbols`.
- `focus_llm`:
  - Mini switch via `FOCUS_USE_MINI` (classify/judge/rescore).
  - Debug `--debug-llm` and `.env` auto‑loading.
  - Follow‑up best‑of selection; plan enrichment with filename globs.
  - Answer prompt emphasizes structured sections (MSG FIELDS, URDF JOINTS, NESTED MSGS, SYMBOLS).
- Benchmarking:
  - Heuristic or LLM grading (`--llm-grade`) with reasoning; traces saved per question.

## High‑Value Next Steps
- Symbol tracing v2 (multi‑file call sites + richer blocks) for behavior questions.
- Smarter nested msg resolution when types live in different packages/dirs (search strategy & caching).
- Classifier rules for simulator/build intents to inject more targeted filename globs and include globs.
- Presentation: prioritize structured sections first in the answer to maximize grading alignment.

---

Artifacts are under `results/` (e.g., `results/benchmark_results_v14.json` and `results/traces/trace_XX.json`).
