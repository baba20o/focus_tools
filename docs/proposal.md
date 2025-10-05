# Proposal: Focus‑First + Scoped RAG Hybrid Retrieval

This document is a “save zone” for design decisions when we hit crossroads. It proposes how to evolve Focus Tools into a hybrid system that keeps determinism and precision while leveraging semantic recall when strictly needed.

## Objectives
- Preserve Focus‑first determinism: discover → grep → rank → extract → synthesize with grounded citations.
- Add a scoped RAG fallback for questions where relevant evidence is outside code or dispersed (guidelines, troubleshooting, theory).
- Route questions to the right strategy with tight budgets and a single backoff loop.

## Strengths & Gaps (Today)
- Strengths:
  - Structural filters + filename channel surface authoritative files (README, *.msg, *.urdf, robot_actions.py, pyproject.toml, Dockerfile*).
  - Lightweight extractors produce structured context (MSG FIELDS, URDF JOINTS, NESTED MSGS, SYMBOLS).
  - Follow‑up best‑of avoids regressions.
- Gaps:
  - Practice/troubleshooting guidance often lives in wikis/blogs; repo lacks direct evidence.
  - Complex behavior questions (multi‑file, multi‑hop) need simple tracing beyond a single symbol.
  - When evidence is truly missing, answers are “insufficient,” which is correct but graded low in Q/A style tests.

## Proposed Architecture (Hybrid)
1) Router/Planner
- Input: question, bases, policy (allow_rag: bool), budgets.
- Output: plan {category, focus knobs, filename_globs, include_globs, content_first, not_parent, budgets, allow_rag}.
- Categories (initial): definition/path | schema | config/launch | symbol/behavior | troubleshooting | docs/guidelines.

2) Focus Phase (Deterministic)
- Run focus_probe with plan (filename channel + include‑all if globs present).
- Rank with authority boosts; extract structures (msg nested, urdf joints, symbols).

3) Sufficiency Gate
- Score(b) = files_with_hits + α·authority_count + β·extraction_signals + γ·cluster_concentration − penalties.
- If score ≥ threshold → answer now.
- Else, attempt exactly one Focus “broaden” (already implemented follow‑up) and keep best‑of.

4) Scoped RAG Fallback (Optional)
- If still insufficient AND allow_rag:
  - Scope RAG to Focus path_prefixes (and/or plan filename_globs) with small k.
  - Merge RAG chunks as “semantic” evidence with clear provenance.

5) Synthesis/Answer
- Build compact summary with structured sections first (MSG FIELDS, NESTED MSGS, URDF JOINTS, SYMBOLS), then snippets/peeks.
- Prompts emphasize using structured sections, cite file:line for claims, and refuse speculation.

6) Grading/Analytics
- Optional mini‑LLM grading for experiments; log sufficiency, category, authority hits, latency, and costs to tune the router.

## Question Taxonomy → Retrieval Strategies
- Definition/Path
  - filename_globs: README.md (keyword dir), authoritative docs; include‑all + definition boost.
- Schema (.msg/.idl/.srv)
  - include: *.msg, *.idl, *.srv, *.md; extract top‑level + nested (depth 2); filename_globs: Type.msg if symbol known.
- Config/Launch
  - include: *.yaml, *.yml, *.launch.py; filename_globs: pyproject.toml, Dockerfile* for build‑deps class.
- Symbol/Behavior
  - include: *.py, *.cpp, *.hpp; symbol block extraction; cross‑file symbol tracer (call sites + defs).
- Troubleshooting/Guidelines
  - include: README.md, docs, examples/tests; filename_globs: README.md, examples/* where applicable; if insufficient and policy allows → scoped RAG to repos/docs folder.

## Implementation Plan
- Phase 1 (Router + Focus polish)
  - Rule‑based router: map category + plan knobs; keep Mini as optional.
  - Enrich plan with filename_globs by intent (already partly done) and add simulator/build rules.
  - Extend sufficiency score to weight extraction signals more.
- Phase 2 (Scoped RAG Adapter)
  - Define interface: rag.search(question, path_filter=[...], k=N) → [{path, text, meta}].
  - Merge with Focus bundle as a separate section; preserve provenance.
- Phase 3 (Tracing & Extraction v2)
  - Multi‑file symbol tracer: find call sites + def blocks; bound per module.
  - Nested .msg cache across runs; resolve types across packages.
- Phase 4 (Analytics & Tuning)
  - Log router decisions, sufficiency scores, grades; iterate thresholds.

## Interfaces & Policy
- Router API (pseudo):
  - plan = route(question, bases, policy) → {category, include_globs, filename_globs, content_first, not_parent, budgets, allow_rag}
- Focus Runner: focus_probe(bases, plan) → bundle
- RAG Adapter (pluggable): rag.search(question, path_filter, k)
- Merge: merge(bundle, rag_chunks) → bundle′ (semantic section added)
- Policy knobs: allow_rag (bool), rag_k (int), max_tokens (int), timeouts.

## Success Metrics
- Accuracy: ↑ average grade on mixed sets (repo facts + practice) with strict grounding.
- Cost/Latency: bounded (router uses Focus fast path; RAG only once, scoped).
- Explainability: every answer cites files/lines; RAG chunks show path provenance.

## Risks & Mitigations
- Hallucination: keep Focus‑first; RAG is scoped and clearly labeled; refuse unsupported claims.
- Complexity creep: one follow‑up, one scoped RAG call max; budgets enforced.
- Domain variance: use router categories/filename channel/authority boosts instead of per‑question rules.

## Open Questions
- Where to source “adjacent docs”: local wiki clones? Dedicated docs base path?
- Which RAG engine to integrate (your repo) and its interfaces/auth.
- Policy defaults for categories that commonly require RAG (troubleshooting/guidelines).

## Integration with Your RAG Repo (Preview)
- Inputs expected: question, optional path_filter (from Focus), k.
- Outputs expected: chunks with path/text/score; we’ll merge them under a RAG section.
- Security/Policy: respect path allowlists; no network calls unless enabled.

---

This proposal keeps Focus Tools as the precision core, adds a router to pick the right strategy, and uses RAG surgically when the evidence isn’t in the repo. It’s designed to scale across domains without curve‑fitting and to remain explainable end‑to‑end.

---

## Post RAG Engine Analysis (EIS_CHATBOT)

What we learned reviewing `C:\tests\EIS_CHATBOT` and how it informs the hybrid design.

### Engine Capabilities Observed
- RAG pipeline with intent routing, hybrid ranking (vector + BM25), query rewriter with cache (TTL/size/versioned), and optional compact traces.
- Source gating and link mapping (GitHub repos/docs, Notion, JIRA) with centralized link utils.
- Backend endpoints + Slack bot plumbing (not essential for integration but useful for ops/UX).

### Integration Fit with Focus Tools
- Keep Focus as the precision scoper and extractor; use EIS RAG for scoped semantic recall when Focus evidence is insufficient.
- Pass Focus `path_prefixes` and plan `file_name_globs` to RAG as a `path_filter` to keep retrieval focused and low‑noise.
- Merge retrieved chunks into the Focus bundle labeled as a semantic section; preserve provenance for explainability.

### Adapter Options
- Import‑based adapter (simple):
  - Pros: direct Python call, no network; faster and minimal plumbing.
  - Cons: tighter coupling; must align PYTHONPATH (env `EIS_CHATBOT_PATH`) and dependency versions.
- REST adapter (decoupled):
  - Pros: process isolation, stable API (`POST /api/rag/search`) with `{"question","path_filter","k"}`; easier to scale independently.
  - Cons: requires small API addition and service availability; some overhead.

### Proposed Interface Contract (either path)
- Input: `question: str`, `path_filter: list[str]`, `k: int` (small, e.g., 3–5).
- Output: `[{ path|url, text|snippet, score, source_type, doc_type }]` (stable keys used when merging into Focus bundle).

### Router/Policy Refinements
- Categories likely to need RAG fallback: troubleshooting, guidelines/docs, broad “how to” when repo lacks anchors.
- Allow exactly one RAG call after Focus follow‑up; bound `k`, apply path_filter; budget guard remains in Focus.
- Respect source gating (e.g., restrict to “repos/docs” unless Notion/JIRA are explicitly allowed locally).

### Synthesis
- Present structured Focus evidence first (MSG FIELDS, NESTED MSGS, URDF JOINTS, SYMBOLS), then include a short “RAG CHUNKS” list when present with title/snippet/link.
- Keep refusal to speculate when both Focus + scoped RAG are weak; ask for the specific missing files.

### Success Criteria (hybrid)
- ↑ Accuracy on practice/troubleshooting sets with minimal latency/cost increase.
- Strong explainability via provenance (files/lines/links) and traces on both sides.

---

## Proposal Comparison (Before vs After RAG Analysis)

### Before (RAG‑agnostic hybrid plan)
- Route → Focus → Sufficiency → (optional) Scoped RAG → Synthesize.
- Filename channel + authority weighting + extractors were central to improving Focus.
- Scoped RAG was suggested conceptually but without a concrete engine interface.

### After (with EIS RAG engine knowledge)
- Same high‑level flow, now with a concrete, pluggable adapter:
  - Import or REST adapter to `eis_chatbot.services.rag_engine`/`vector_store` with a `path_filter` parameter.
  - Leverage existing intent routing, hybrid ranking, rewriter cache, and tracing.
- Focus router enriched with category‑specific filename globs and include rules (e.g., robot_actions.py, pyproject.toml, Dockerfile*; README/examples for practice docs).
- Explicit policy knobs (allow_rag per category) and a single backoff loop with best‑of selection.

### Analysis
- The initial proposal holds up: Focus remains the deterministic “laser,” RAG becomes a scoped, last‑mile recall layer.
- The EIS engine fills the exact gap we observed in ROS2 troubleshooting/guidance questions; many answers live in docs/wikis beyond the code tree.
- Integration risk is manageable: path filtering + provenance ensures explainability, and budgets keep costs bounded.

---

## Next Steps (Implementation Routes)

1) Choose Adapter:
   - Import‑based (faster to implement) or REST API (`/api/rag/search`).

2) Implement Adapter:
   - `focus_rag_adapter.py` in Focus repo; accepts question + path_filter + k; returns chunks.
   - Add env `EIS_CHATBOT_PATH` for import‑based path resolution (if used).

3) Wire Router / Policy:
   - Route troubleshooting/guidelines to allow RAG fallback; leave definition/schema to Focus‑only by default.
   - Continue using filename channel + include‑all when globs present.

4) Merge in Focus Flow:
   - If Focus insufficient after follow‑up, call RAG adapter once; merge chunks; rebuild summary; synthesize.

5) Validate:
   - Run mixed sets (AMP + ROS2) with `FOCUS_USE_MINI=1` and `--llm-grade` to measure gains; review traces.

6) Iterate:
   - Tune thresholds/weights and category rules using sufficiency logs and grader reasons.
