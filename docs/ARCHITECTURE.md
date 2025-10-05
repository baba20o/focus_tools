# Focus Tools - Architecture & LLM Integration Guide

**Version 1.0 | October 2025**

---

## 📐 System Architecture

### High-Level Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      USER QUESTION                           │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              LLM COMMANDER (Router + Orchestrator)           │
│  • Profile selection (rules-based or LLM-inferred)          │
│  • Parameter synthesis (keyword, pattern, filters)          │
│  • Quality gates (confidence scoring)                       │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                   FOCUS TOOLS SUITE                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ focus_tree   │  │ focus_grep   │  │ focus_probe  │      │
│  │              │  │              │  │              │      │
│  │ Discover     │  │ Search       │  │ All-in-one   │      │
│  │ directories  │→ │ content      │→ │ pipeline     │      │
│  │              │  │              │  │              │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│                           ↓                                  │
│                  ┌─────────────────┐                        │
│                  │ focus_common    │                        │
│                  │ • Config loader │                        │
│                  │ • Profile system│                        │
│                  │ • Alias expansion│                       │
│                  │ • Token budgeting│                       │
│                  │ • Weights/ranking│                       │
│                  └─────────────────┘                        │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                   ENRICHED CONTEXT BUNDLE                    │
│  • Top-N ranked files (by relevance)                        │
│  • Snippets with context (±N lines)                         │
│  • Structural previews (head/tail peeks)                    │
│  • Cluster analysis (directory concentration)               │
│  • Token estimates (budget compliance)                      │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              LLM SYNTHESIZER (Answer Generator)              │
│  • Evidence-grounded generation                             │
│  • Source citation (file:line)                              │
│  • Confidence scoring                                       │
│  • Follow-up probe requests (optional)                      │
└──────────────────────┬──────────────────────────────────────┘
                       ↓
                   ANSWER
```

---

## 🔄 Data Flow

### 1. **Input Layer**
```python
{
    "question": "How do I teleop Spot with RViz?",
    "context": {
        "base_paths": ["./bdai-main"],
        "preferences": {...}
    }
}
```

### 2. **Routing Layer**
```python
{
    "strategy": "profile",  # or "synthesize"
    "profile": "teleop-scout",
    "keyword": "spot",
    "overrides": {}
}
```

### 3. **Retrieval Layer** (focus_probe)
```python
{
    "dirs_found": 7,
    "files_scanned": 234,
    "files_with_hits": 15,
    "top_files": [
        {
            "path": ".../spot_rviz_teleop.launch.py",
            "score": 12.5,
            "hits": 5,
            "snippets": [...],
            "peek_head": [...],
            "peek_tail": [...]
        },
        ...
    ],
    "clusters": {
        "ws/src/spot_utilities/launch": 6,
        "ws/src/spot_driver": 2
    },
    "token_estimate": 3200
}
```

### 4. **Synthesis Layer**
```python
{
    "answer": "To teleop Spot with RViz, run:\n...",
    "sources": [
        "spot_rviz_teleop.launch.py:42-58",
        "spot_utilities/README.md:89-102"
    ],
    "confidence": 0.95,
    "method": "teleop-scout profile"
}
```

---

## 🧠 LLM Integration Patterns

### Pattern 1: **Profile-First (Fast Path - 80% of queries)**

```python
def pattern_profile_first(question: str) -> dict:
    """
    Use when question maps to known profile.
    Latency: 8-12s | Cost: $0.01 | Accuracy: 90%+
    """
    # Rule-based routing
    profile = match_profile(question)  # Simple keyword rules
    
    # Run probe
    bundle = focus_probe.run(
        keyword=extract_keyword(question),
        profile=profile,
        budget_tokens=8000
    )
    
    # Synthesize
    if bundle.files_with_hits >= 3:
        return llm.generate(question, bundle)
    else:
        return pattern_synthesize(question)  # Fallback
```

**When to use:**
- Question contains clear intent keywords ("launch", "teleop", "config")
- Similar questions have been answered before
- Speed is critical

**Examples:**
- "How do I launch X?"
- "What does function Y do?"
- "Where is Z configured?"

---

### Pattern 2: **Synthesize (Flex Path - 15% of queries)**

```python
def pattern_synthesize(question: str) -> dict:
    """
    Use when no profile matches or question is unusual.
    Latency: 12-18s | Cost: $0.02 | Accuracy: 85%+
    """
    # LLM generates probe parameters
    params = llm.synthesize_probe_params(
        question=question,
        available_profiles=list_profiles(),
        guidelines=PROBE_SYNTHESIS_RUBRIC
    )
    
    # Run probe with synthesized params
    bundle = focus_probe.run(**params)
    
    # Quality gate
    if bundle.is_weak():
        # Broaden once
        relaxed = relax_filters(params)
        bundle = focus_probe.run(**relaxed)
    
    return llm.generate(question, bundle)
```

**When to use:**
- No profile matches
- Novel question type
- Cross-domain query

**Examples:**
- "Compare authentication methods across services"
- "Find all TODO comments in recent commits"
- "Which configs affect network latency?"

---

### Pattern 3: **Iterative Refinement (Complex Path - 5% of queries)**

```python
def pattern_iterative(question: str) -> dict:
    """
    Use for complex multi-step investigations.
    Latency: 20-40s | Cost: $0.05 | Accuracy: 90%+
    """
    # Initial probe
    bundle1 = pattern_profile_first(question)
    
    # LLM decides: sufficient?
    decision = llm.evaluate_sufficiency(question, bundle1)
    
    if decision.sufficient:
        return llm.generate(question, bundle1)
    
    # Follow-up probe with refined params
    refined_params = llm.refine_probe(
        question=question,
        initial_bundle=bundle1,
        gaps=decision.gaps
    )
    
    bundle2 = focus_probe.run(**refined_params)
    
    # Merge context
    merged = merge_bundles(bundle1, bundle2)
    
    return llm.generate(question, merged)
```

**When to use:**
- Initial results are close but incomplete
- Question has multiple sub-questions
- Cross-reference needed

**Examples:**
- "How do components A and B interact?"
- "What's the full lifecycle of X?"
- "Find all dependencies of Y"

---

### Pattern 4: **Scoped RAG Fallback (Rare - 5% of queries)**

```python
def pattern_scoped_rag(question: str) -> dict:
    """
    Use when structural search fails but directories are known.
    Latency: 25-50s | Cost: $0.08 | Accuracy: 75%+
    """
    # Try structural search first
    bundle = pattern_synthesize(question)
    
    if bundle.confidence < 0.5:
        # RAG scoped to directories probe found
        rag_chunks = rag.search(
            question,
            path_filter=bundle.path_prefixes,  # KEY: scoped to probe dirs
            k=5  # Small k, since scoped
        )
        
        # Merge
        context = {
            "structural": bundle.top_files,
            "semantic": rag_chunks
        }
        
        return llm.generate(question, context)
    
    return llm.generate(question, bundle)
```

**When to use:**
- Structural search found directories but wrong files
- Question requires deep semantic understanding
- Concept-based search (not keyword)

**Examples:**
- "What design patterns are used?"
- "Explain the error handling philosophy"
- "How is state managed?"

---

## 🎛️ Configuration System

### Hierarchy (Most specific wins)

```
1. CLI arguments          (highest priority)
   ↓
2. Per-repo config       (.focus_config.yaml in repo root)
   ↓
3. User global config    (~/.focus_config.yaml)
   ↓
4. Tool defaults         (coded in focus_common.py)
```

### Profile Anatomy

```yaml
profiles:
  teleop-scout:
    # Discovery filters
    must_parent_all: [ws, src]        # Path must contain ALL
    must_parent: [ros2]                # Path must contain ANY
    not_parent: [tests, examples]     # Path must contain NONE
    name_regex: "spot_.*"              # Directory name matches
    name_exact: [spot_teleop]          # Or exact match
    
    # Content search
    pattern: "(teleop|rviz|launch|cmd_vel)"  # Grep pattern
    regex: true                        # Treat as regex
    ignore_case: true                  # Case-insensitive
    
    # File filtering
    include: ["*.py", "*.launch.py", "*.md"]  # File types
    exclude: ["*.pyc", "*.log"]        # Exclude patterns
    
    # Ranking & limits
    weights: {.launch.py: 2.0, .md: 1.5}  # File type importance
    top_files: 8                       # Return top N
    context: 3                         # Lines around matches
    
    # Enrichment
    peek: true                         # Include head/tail
    peek_head_lines: 80
    peek_tail_lines: 40
    read_bytes: 12000                  # Include full content
    ascii_tree: false                  # Directory trees
    
    # Budget
    budget_tokens: 8000                # Token limit
```

---

## 📊 Quality Metrics

### Probe Quality Score

```python
def compute_quality_score(bundle: dict) -> float:
    """
    Returns 0.0-1.0 confidence score.
    """
    score = 0.0
    
    # File count (0.3 weight)
    files_score = min(bundle.files_with_hits / 5, 1.0) * 0.3
    
    # Cluster concentration (0.4 weight)
    # High when most files from same directory
    cluster_score = max_cluster_concentration(bundle.clusters) * 0.4
    
    # Token efficiency (0.2 weight)
    # High when token_estimate is reasonable
    token_score = (1.0 - min(bundle.token_estimate / 10000, 1.0)) * 0.2
    
    # Hit density (0.1 weight)
    # High when few files have many hits
    density_score = compute_hit_density(bundle.top_files) * 0.1
    
    return files_score + cluster_score + token_score + density_score

def is_weak(bundle: dict) -> bool:
    """
    True if bundle likely needs broadening or RAG fallback.
    """
    return (
        bundle.files_with_hits < 3 or
        compute_quality_score(bundle) < 0.5 or
        max_cluster_concentration(bundle.clusters) < 0.3
    )
```

### Answer Quality Evaluation

```python
def evaluate_answer(question: str, answer: str, bundle: dict) -> dict:
    """
    Post-generation quality check.
    """
    return {
        "has_sources": count_citations(answer) > 0,
        "cites_top_files": citations_match_bundle(answer, bundle),
        "confidence": answer_confidence_score(answer),
        "token_efficiency": len(answer) / bundle.token_estimate,
        "needs_followup": answer.contains("insufficient information")
    }
```

---

## 🚀 Deployment Patterns

### Minimal Agent (Starter)

```python
import focus_probe
import openai

SIMPLE_PROFILES = {
    "launch": "teleop-scout",
    "doc": "doc-hunter",
    "config": "config-audit",
    "message": "msg-schema-hunter"
}

def simple_agent(question: str, base_path: str) -> str:
    # Simple keyword routing
    profile = None
    for keyword, prof in SIMPLE_PROFILES.items():
        if keyword in question.lower():
            profile = prof
            break
    
    # Run probe
    bundle = focus_probe.run(
        keyword=extract_first_word(question),
        pattern=question,  # Use question as pattern
        base=base_path,
        profile=profile,
        top_files=8,
        peek=True,
        budget_tokens=8000
    )
    
    # LLM synthesis
    prompt = f"""
    Question: {question}
    
    Evidence:
    {format_bundle(bundle)}
    
    Answer the question using only the evidence. Cite file:line.
    """
    
    return openai.chat(prompt)
```

---

### Production Agent (Full Featured)

```python
class FocusAgent:
    def __init__(self, config_path: str, cache_dir: str):
        self.config = load_config(config_path)
        self.cache = CacheLayer(cache_dir)
        self.analytics = AnalyticsLogger()
        
    def answer(self, question: str, base_paths: List[str]) -> dict:
        # Route
        route = self.route_question(question)
        
        # Check cache
        cache_key = self.cache.key(question, route, base_paths)
        if cached := self.cache.get(cache_key):
            return cached
        
        # Probe (with retry logic)
        bundle = self.probe_with_quality_gates(
            question=question,
            route=route,
            base_paths=base_paths
        )
        
        # Synthesize
        answer = self.synthesize_answer(question, bundle)
        
        # Log
        self.analytics.log({
            "question": question,
            "route": route,
            "bundle_stats": bundle.stats,
            "answer_quality": evaluate_answer(question, answer, bundle)
        })
        
        # Cache
        self.cache.set(cache_key, answer)
        
        return answer
    
    def probe_with_quality_gates(self, question, route, base_paths):
        """Implements Pattern 3: Iterative Refinement"""
        bundle = focus_probe.run(
            **route.params,
            bases=base_paths
        )
        
        if is_weak(bundle):
            # Try once with relaxed filters
            relaxed = relax_filters(route.params)
            bundle = focus_probe.run(**relaxed, bases=base_paths)
            
            if is_weak(bundle):
                # Scoped RAG fallback
                rag_chunks = self.rag.search(
                    question,
                    path_filter=bundle.path_prefixes
                )
                bundle = merge(bundle, rag_chunks)
        
        return bundle
```

---

## 🧪 Testing & Validation

### Unit Tests

```python
def test_profile_selection():
    assert match_profile("how to launch spot") == "teleop-scout"
    assert match_profile("what fields in MultiJointTraj") == "msg-schema-hunter"

def test_quality_scoring():
    weak_bundle = {"files_with_hits": 1, "clusters": {}}
    assert is_weak(weak_bundle) == True
    
    strong_bundle = {"files_with_hits": 8, "clusters": {"dir1": 6}}
    assert is_weak(strong_bundle) == False
```

### Integration Tests

```python
def test_end_to_end():
    question = "How do I teleop Spot?"
    answer = agent.answer(question, ["./test-repo"])
    
    assert "launch" in answer.lower()
    assert len(answer.sources) > 0
    assert answer.confidence > 0.7
```

### Benchmark Suite

```python
BENCHMARK_QUESTIONS = [
    {"q": "How do I launch Spot teleop?", "expected_profile": "teleop-scout"},
    {"q": "What fields in MultiJointTraj?", "expected_profile": "msg-schema-hunter"},
    # ... 50 more questions
]

def run_benchmark():
    results = []
    for item in BENCHMARK_QUESTIONS:
        answer = agent.answer(item["q"], ["./bdai-main"])
        grade = human_grade(item["q"], answer)  # or LLM judge
        results.append({
            "question": item["q"],
            "grade": grade,
            "latency_ms": answer.latency,
            "tokens": answer.token_count,
            "cost": estimate_cost(answer)
        })
    
    print(f"Avg grade: {mean([r['grade'] for r in results])}")
    print(f"Avg latency: {mean([r['latency_ms'] for r in results])}ms")
    print(f"Avg cost: ${mean([r['cost'] for r in results])}")
```

---

## 🔮 Future Enhancements

### Phase 1 (Next 2 Weeks)
- [ ] LLM router implementation
- [ ] Probe parameter synthesis
- [ ] Quality gates + auto-broaden
- [ ] Basic caching

### Phase 2 (Month 1)
- [ ] Analytics dashboard
- [ ] Profile auto-tuning from logs
- [ ] Multi-repo support
- [ ] Parallel probe execution

### Phase 3 (Month 2-3)
- [ ] AST-aware parsing (function/class extraction)
- [ ] Dependency graph traversal
- [ ] Interactive wizard mode
- [ ] Web UI

---

## 📞 Support & Feedback

This is a research/internal tool. For questions or collaboration:
- Review the individual tool READMEs
- Check the examples in each file

---

## ♻️ Recent Retrieval Enhancements

- Filename channel: focus_probe can promote candidate files by name using --file-name-regex/--file-name-globs with a configurable --filename-weight. This surfaces canonical targets (e.g., robot_actions.py, pyproject.toml) even when content matches are sparse.
- Include-all breadth: --include-all disables include globs in both content-first and normal modes, ensuring discovery breadth when needed.
- Authority weighting: default (mergeable) boosts for .msg/.idl/.srv/.urdf/.xacro/.toml/.xml and authority dirs (msg/srv/urdf/description/action).
- Structured extractors: peeks now include lightweight extractions when applicable:
  - .msg → extracted_msg_fields
  - .urdf/.xacro → extracted_urdf_joints
  These appear in the bundle/answer summary to guide LLMs without extra tokens.

## 🧪 Mini‑LLM Switch & Debugging

- Mini switch: Set FOCUS_USE_MINI=1 to enable mini‑LLM for classify/judge/rescoring; answer uses OPENAI_MODEL. With it off (default), classify is rule‑based and judge assumes sufficient.
- Debugging: pass --debug-llm to focus_llm (or set FOCUS_DEBUG_LLM=1) to print prompts/outputs to stderr. Traces are still written to results/traces/ when running via the benchmark.
- Run with `--debug` for troubleshooting

---

**Remember:** Precision beats scale when you have intelligence to aim. 🎯
