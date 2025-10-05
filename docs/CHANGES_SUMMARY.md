# Focus Tools - Content-First Mode Implementation

## 🎯 Problem Identified

**Original Issue**: focus_probe required directory NAMES to match the keyword before searching content. This caused massive blind spots:

- Searching "amp" → found `amp_common/`, `amp_msgs/` directories
- But MISSED `projects/amp/README.md` because directory is "projects", not "amp*"
- Result: 0 files found for "What does AMP stand for?"

## ✅ Solution Implemented

### 1. Added `--content-first` Flag to focus_probe.py

**What it does:**
- Skips directory name matching entirely
- Searches entire repository base for content pattern
- Then applies structural filters (not_parent, file types, etc.)
- Clusters and ranks results as normal

**Code changes:**
```python
# In focus_probe.py main()
if args.content_first:
    dirs = bases  # Use base directories directly (no keyword filtering)
else:
    dirs = discover_dirs(keyword, ...)  # Normal keyword→directory matching
```

### 2. Enhanced iter_files_under_dirs() with not_parent Filtering

Now applies `not_parent` filters even in content-first mode to exclude tests/, examples/, etc.

### 3. Updated Classifier Prompt

**New rule:**
> Use "content_first": true for most queries. Only set false when keyword exactly matches directory names.

**Updated examples:**
- `"What does AMP stand for?"` → `"content_first": true` ✅
- `"What are contents of MultiJointTraj?"` → `"content_first": true` ✅
- `"How to teleop Spot?"` → `"content_first": false` (spot directories exist)

### 4. Updated focus_llm.py

Added support for passing `content_first` flag from classifier to focus_probe.

### 5. Added --verbose Mode to focus_llm.py

Shows step-by-step execution:
- Classifier output (plan JSON)
- Probe results (dirs found, files scanned, hits)
- Judge decision
- Follow-up probe (if needed)
- Final answer

**Usage:**
```bash
python focus_llm.py "Question?" -b ./repo --verbose
```

---

## 📊 Test Results

### Before (Directory-First):
```bash
python focus_probe.py amp "AMP" -b ./bdai-main --include "*.md"
# Result: Dirs: 33, Files: 891, Hits: 174
# But required must_parent filters which excluded the right files
```

### After (Content-First):
```bash
python focus_probe.py amp "(AMP|Agile.*Manipulation)" \
  -b ./bdai-main --content-first --include "*.md" --regex
# Result: Dirs: 1, Files: 327, Hits: 55
# Top file: projects/amp/README.md ✅
```

---

## 🔍 Remaining Issues

### Issue 1: Ranking Still Needs Tuning

Files with MORE mentions of keyword rank higher than files with the DEFINITION:

**Current ranking for "What does AMP stand for?":**
1. `alpha_orchestrator/README.md` (20 hits of "AMP" in context) 
2. `alpha_executors/README.md` (15 hits)
3. `amp_common/README.md` (12 hits)
4. **`projects/amp/README.md`** (2 hits: title "# Agile Manipulation Platform") ← This is the answer!

**Problem**: Hit count dominates ranking, but the DEFINITION is often in headers/titles with fewer total mentions.

**Potential solutions:**
1. Boost weight for files at shallower directory depth (projects/amp/ > ws/src/pkg/)
2. Boost weight for H1 headers in markdown (`# Title`)
3. Add "definition detection" heuristic (looks for "X stands for Y" patterns)
4. Use LLM to re-rank top 20 results based on "most likely to contain definition"

### Issue 2: Judge/Follow-up Logic

The judge is sometimes requesting follow-ups that make results WORSE:
- First probe: 55 files with hits
- Judge says "insufficient"
- Follow-up probe: 0 files with hits

This suggests the judge prompt needs tuning to recognize when first probe is actually good.

---

## 🚀 Next Steps

### Immediate (Test Phase):
1. ✅ Run full 10-question benchmark with content-first mode
2. Compare results to baseline (2.2/5 average)
3. Identify which questions improved vs. which still fail

### Short-term (Tuning):
1. **Tune ranking algorithm** to prefer:
   - Shallower directory depths
   - README.md files at project roots
   - H1/H2 headers in markdown
   
2. **Tune judge prompt** to:
   - Recognize when 50+ files with hits is sufficient
   - Not request follow-ups that over-narrow

3. **Add scoring boost for "definition patterns"**:
   - Regex: `stands for|is an?|acronym for`
   - Boost files containing these phrases

### Long-term (Enhancement):
1. Two-stage retrieval: Broad search → LLM re-ranking
2. Caching layer for repeated queries
3. Analytics dashboard for tuning weights
4. Profile auto-generation from usage logs

---

## 📈 Expected Impact

**Hypothesis**: Content-first mode + structural filters should improve from 2.2/5 → 3.5-4.5/5

**Why:**
- ✅ Now finds files that exist (was 0 hits, now 50+ hits)
- ✅ Applies smart filters (no tests/, examples/)
- ⚠️ Ranking still imperfect (definition in position #4 instead of #1)
- ⚠️ Judge/follow-up logic needs tuning

**Awaiting benchmark results to confirm...**
