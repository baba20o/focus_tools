# Focus Tools - Quick Reference Card

**One-page cheat sheet for daily use**

---

## 🎯 **Most Common Commands**

### **1. How to Launch / Run Something**
```bash
python focus_probe.py <system> -b <repo> \
  --profile teleop-scout \
  --top-files 8 --peek --json
```

### **2. Find API / Function Definition**
```bash
python focus_probe.py <function_name> -b <repo> \
  --include "*.py,*.cpp,*.md" \
  --pattern "def <function>|class.*<function>" \
  --regex --peek --json
```

### **3. Message / Schema Fields**
```bash
python focus_probe.py <MessageName> -b <repo> \
  --include "*.msg,*.srv,*.idl" \
  --profile msg-schema-hunter \
  --json
```

### **4. Configuration Parameters**
```bash
python focus_probe.py <param> -b <repo> \
  --include "*.yaml,*.yml" \
  --profile config-audit \
  --json
```

### **5. Documentation Search**
```bash
python focus_probe.py docs -b <repo> \
  --profile doc-hunter \
  --pattern "<topic>" \
  --include "*.md,*.rst" \
  --json
```

---

## 🔧 **Common Flags**

| Flag | Purpose | Example |
|------|---------|---------|
| `-b <path>` | Base path to search | `-b ./repo` |
| `--profile <name>` | Use predefined profile | `--profile teleop-scout` |
| `--include <globs>` | File types to search | `--include "*.py,*.md"` |
| `--exclude <globs>` | File types to skip | `--exclude "*.min.js"` |
| `--must-parent <dirs>` | Must be under these dirs | `--must-parent src,ws` |
| `--not-parent <dirs>` | Exclude these dirs | `--not-parent tests` |
| `--regex` | Treat pattern as regex | `--regex` |
| `-i` | Case-insensitive | `-i` |
| `--top-files N` | Return top N results | `--top-files 10` |
| `--peek` | Include head/tail preview | `--peek` |
| `--budget-tokens N` | Trim to N tokens | `--budget-tokens 8000` |
| `--json` | Output JSON | `--json` |
| `--debug` | Verbose logging | `--debug` |

---

## 📋 **Built-in Profiles**

From `.focus_config.yaml`:

| Profile | Use For | Key Features |
|---------|---------|--------------|
| `teleop-scout` | Launch/run commands | Prioritizes `.launch.py` files |
| `doc-hunter` | Documentation | Searches `*.md`, `*.rst` in docs/ |
| `config-audit` | Config parameters | Targets `*.yaml`, `*.yml` |
| `msg-schema-hunter` | ROS messages | Prioritizes `.msg`, `.srv`, `.idl` |

---

## 🎭 **Quick Patterns**

### **Pipe focus_tree → focus_grep**
```bash
python focus_tree.py <keyword> -b <repo> --paths-only | \
python focus_grep.py "<pattern>" --stdin-paths --regex -i --json
```

### **Search Multiple Repos**
```bash
python focus_probe.py <keyword> "<pattern>" \
  -b ./repo1 -b ./repo2 -b ./repo3 \
  --json
```

### **Export to File**
```bash
python focus_probe.py ... --json > results.json
```

### **Debug Mode**
```bash
python focus_probe.py ... --debug 2> debug.log
```

---

## 🐛 **Troubleshooting**

| Problem | Solution |
|---------|----------|
| "No directories found" | Check aliases in config, try `--debug` |
| "Too many results" | Add `--not-parent tests` or tighten `--include` |
| "Wrong files ranked high" | Adjust `weights` in config or create custom profile |
| "Token budget exceeded" | Use `--budget-tokens 8000` or reduce `--top-files` |
| "Slow search" | Add `--not-parent build,dist,node_modules` |

---

## 📊 **Config File Locations**

```
~/.focus_config.yaml           # Global (your personal defaults)
./repo/.focus_config.yaml      # Per-repo (team shared)
--config ./custom.yaml         # One-off override
```

**Priority:** CLI args > per-repo > global > tool defaults

---

## 💡 **Pro Tips**

1. **Start broad, then narrow:**
   ```bash
   # First: see what's there
   python focus_probe.py spot "teleop" -b ./repo --top-files 20
   
   # Then: narrow down
   python focus_probe.py spot "teleop" -b ./repo \
     --must-parent src --not-parent tests --top-files 8
   ```

2. **Use `--peek` for structure preview:**
   - See first 80 + last 40 lines without reading full file
   - Helps LLM understand file layout

3. **Token budgeting is your friend:**
   - Always use `--budget-tokens 8000` for LLM inputs
   - Prevents context overflow

4. **Profile = team knowledge:**
   - If you run the same query twice, make a profile
   - Share `.focus_config.yaml` in your repo

5. **Cache manually for demos:**
   ```bash
   python focus_probe.py ... --json > cache/query_1.json
   # Instant replay later
   cat cache/query_1.json | jq .
   ```

---

## 🚀 **Performance Expectations**

| Repo Size | Scan Time | Typical Results |
|-----------|-----------|-----------------|
| Small (< 100 files) | 1-3s | 3-8 relevant files |
| Medium (100-1K files) | 3-8s | 5-15 relevant files |
| Large (1K-10K files) | 8-20s | 8-20 relevant files |
| Huge (10K+ files) | 20-60s | 10-30 relevant files |

**Note:** Use `--not-parent build,dist,node_modules` to speed up large repos

---

## 📞 **Help**

```bash
python focus_probe.py --help       # Full CLI reference
python focus_tree.py --help        # Directory discovery
python focus_grep.py --help        # Content search
```

**Documentation:**
- `README.md` - Overview
- `ARCHITECTURE.md` - System design
- `README-focus_probe.md` - Detailed usage

---

## 🎯 **Remember**

**Profiles > Manual Flags** — If you're typing the same flags twice, make a profile.

**Structural > Semantic** — Use path filters to eliminate noise before searching content.

**Peek > Full Read** — Preview structure before committing to full file reads.

**Budget > Bloat** — Always set token limits for LLM inputs.

---

**Happy Hunting! 🎯🔫**
# Quick Reference

## Common Commands

- Probe (content-first, broad):
  - `python focus_probe.py amp "(teleop|rviz)" -b ./repo --content-first --json --top-files 8 --peek`

- Include all filetypes (no include globs):
  - `python focus_probe.py docs guide -b ./repo --include-all --json`

- Filename authority channel:
  - `python focus_probe.py alpha . -b ./repo --content-first --file-name-globs robot_actions.py --json`

- Peeks (defaults head=400, tail=80):
  - `python focus_probe.py alpha wave -b ./repo --peek --json`

- Focus read (bounded lines/range):
  - `python focus_read.py file.py --head 200 --json`

- Benchmark (env from .env):
  - `python scripts/benchmark.py -b C:\\path\\to\\repo --csv data/AMP_Test_Questions.csv --auto-grade --trace-dir results/traces --llm-verbose`
  - Add `--llm-debug` to print prompts/outputs.

## Switches & Env

- `FOCUS_USE_MINI=1` → enable mini‑LLM for classify/judge/rescore; answer uses `OPENAI_MODEL`.
- `FOCUS_DEBUG_LLM=1` → print LLM prompts/outputs to stderr (also available via `--debug-llm`).
- `.env` keys: `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_MINI_MODEL`.

## New Flags (focus_probe)

- `--include-all` → disable include globs.
- `--file-name-regex`, `--file-name-globs` → promote files by name.
- `--filename-weight` → multiplier for filename matches.
