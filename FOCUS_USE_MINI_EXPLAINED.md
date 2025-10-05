# FOCUS_USE_MINI Environment Variable Explained

## Current Command
```powershell
$env:FOCUS_USE_MINI='0'; python scripts/benchmark.py -b C:\test_repos\bdai-main ...
```

## Behavior

### FOCUS_USE_MINI=0 (DEFAULT - What agent is using)

**What happens:**
- **Classifier**: Uses rule-based logic (`_rule_based_plan()`) - NO LLM call
- **Judge**: Always returns `{"sufficient": True}` - NO LLM call  
- **Answer**: Uses main LLM (gpt-5) - YES LLM call

**Characteristics:**
- ✅ Cost: **Lower** (1-2 LLM calls per question vs 3-4)
- ✅ Speed: **Faster** (no classifier/judge LLM overhead)
- ❌ Accuracy: **Lower** (simple pattern matching instead of intelligent classification)

### FOCUS_USE_MINI=1 (Full LLM pipeline)

**What happens:**
- **Classifier**: Uses LLM (OPENAI_MINI_MODEL, e.g., gpt-5-mini) to plan probe (may include filename globs) - YES LLM call
- **Judge**: Uses LLM (OPENAI_MINI_MODEL) to assess evidence quality (one bounded follow-up) - YES LLM call
- **Rescore**: Uses LLM (OPENAI_MINI_MODEL) to rank file heads (60/40 with probe rank) - YES LLM call
- **Answer**: Uses main LLM (OPENAI_MODEL) - YES LLM call
 - (Optional) Scoped RAG fallback: controlled by `ALLOW_RAG`/`--allow-rag` and router policy, executed once if Focus evidence is weak.

**Characteristics:**
- ✅ Accuracy: **Higher** (intelligent query classification + evidence judging)
- ✅ Features: Uses all Priority 1 improvements (classifier prompts, judge logic)
- ❌ Cost: **Higher** (3-4 LLM calls per question)
- ❌ Speed: **Slower** (additional LLM calls)

## Rule-Based Plan Logic (FOCUS_USE_MINI=0)

When disabled, uses simple keyword matching:

```python
def _rule_based_plan(question: str) -> Dict[str, Any]:
    q = question.lower()
    
    # Default plan
    plan = {
        "keyword": "docs",
        "pattern": question,  # Uses full question as search pattern
        "include": ["*.md", "*.rst", "*.py"],
        "must_parent_any": ["src", "ws"],
        ...
    }
    
    # Teleop/RViz pattern
    if any(k in q for k in ["teleop", "rviz", "launch"]):
        plan["include"] = ["*.launch.py", "*.md", "*.py"]
    
    # Message schema pattern
    elif any(k in q for k in ["message", "msg", "interface"]):
        plan["include"] = ["*.msg", "*.idl", "*.srv", "*.md"]
    
    return plan
```

**Limitations:**
- No intelligent keyword extraction ("What does AMP stand for?" → keyword: "docs", pattern: full question)
- No file type optimization beyond simple keyword matching
- Misses nuances (doesn't detect acronym vs function vs config questions)

## Should the Agent Use FOCUS_USE_MINI=0?

### ✅ Use FOCUS_USE_MINI=0 if:
- **Quick testing/debugging** basic functionality
- **Cost is critical** and questions are simple
- Rule-based patterns match your use case well
- Running many experiments rapidly

### ❌ Use FOCUS_USE_MINI=1 if:
- **Accuracy matters** (benchmark testing)
- Questions are **diverse/complex** (like AMP test questions)
- Want to use **all Priority 1 features** (classifier improvements, judge logic)
- Need intelligent query classification

## Recommendation for Benchmark Testing

**Current**: Agent is using `FOCUS_USE_MINI=0` 
**Should be**: `FOCUS_USE_MINI=1` for accurate benchmarking

### Why?

1. **Your improvements are in the LLM prompts**: The classifier.txt and judge.txt improvements you made in Priority 1 are **only used when FOCUS_USE_MINI=1**

2. **AMP questions need intelligent classification**:
   - "What does AMP stand for?" → Should detect: acronym question, include *.md, boost READMEs
   - Currently with FOCUS_USE_MINI=0: keyword="docs", pattern=full question, generic search

3. **Benchmark v3 results (1.90/5) assumed LLM classification**: If you were using FOCUS_USE_MINI=0, you're not getting the full benefit of your fixes!

## Correct Command

```powershell
# For benchmark testing with full features
$env:FOCUS_USE_MINI='1'; python scripts/benchmark.py `
  -b C:\test_repos\bdai-main `
  --csv data/AMP_Test_Questions.csv `
  --auto-grade `
  --output results/benchmark_results_v9.json `
  --trace-dir results/traces `
  --llm-verbose
```

To print prompts/outputs to console, add `--llm-debug` (or set `FOCUS_DEBUG_LLM=1`).

## Router & RAG Controls (Optional)

- Enable RAG fallback: `ALLOW_RAG=1` or pass `--allow-rag` to focus_llm.
- Router policy file: `docs/router_policy.json` (per-category `allow_rag`, `source_types`, optional `router_mode`).
- CLI overrides:
  - `--router-mode policy|router|auto`
  - `--rag-sources notion,github_docs`

## Verification

Check if classifier is being used:

```bash
# With FOCUS_USE_MINI=0 (rule-based)
$env:FOCUS_USE_MINI='0'
python focus_llm.py "What does AMP stand for?" -b ./repo --verbose
# Output: keyword="docs", pattern="What does AMP stand for?"

# With FOCUS_USE_MINI=1 (LLM classifier)
$env:FOCUS_USE_MINI='1'  
python focus_llm.py "What does AMP stand for?" -b ./repo --verbose
# Output: keyword="amp", pattern="(AMP|Agile.*Manipulation)", include=["*.md","*.rst"]
```

## Cost Comparison

**Per question (10 questions total):**

| Mode | Classifier | Judge | Answer | Total Calls | Est. Cost |
|------|------------|-------|--------|-------------|-----------|
| FOCUS_USE_MINI=0 | 0 | 0 | 1 | **1** | ~$0.01 |
| FOCUS_USE_MINI=1 | 1 | 1 | 1 | **3** | ~$0.03 |

**Full benchmark (10 questions):**
- Mode 0: ~$0.10 total
- Mode 1: ~$0.30 total

**Difference**: ~$0.20 (negligible for accuracy gain)

## Summary

The agent is currently running with `FOCUS_USE_MINI=0`, which:
- ✅ Bypasses LLM classifier (uses simple pattern matching)
- ✅ Bypasses LLM judge (always says "sufficient")
- ❌ **Misses all your Priority 1 classifier/judge improvements!**

**For accurate benchmark results, use `FOCUS_USE_MINI=1`** to enable the full LLM pipeline and test your actual improvements.
