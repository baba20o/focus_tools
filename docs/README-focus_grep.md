# focus_grep

A fast, focused recursive grep with context, file globs, directory excludes, and JSON output. Designed to chain after `focus_tree.py` so you can surface the right lines from the right subtrees before the LLM reads anything heavy.

## Install

Drop `focus_grep.py` on PATH (or run with `python focus_grep.py …`).  
Python 3.9+ recommended.

## Usage

```bash
python focus_grep.py PATTERN [PATH ...]
                     [--regex] [-i|--ignore-case]
                     [--stdin-paths]
                     [--include CSV] [--exclude CSV]
                     [--exclude-dirs NAME ...]
                     [--max-file-bytes N]
                     [-C|--context N]
                     [--per-file-limit N]
                     [--total-limit N]
                     [--json]
```

## Arguments

**`PATTERN`** — literal substring, or regex if `--regex` set.  
*#example (regex):* `"(teleop|wasd|rviz|launch)"`

**`PATH`** — files or directories to search. Optional if you use `--stdin-paths`.

**`--stdin-paths`** — read newline-separated paths from stdin (perfect with `focus_tree.py --paths-only`).

**`--regex`** — treat PATTERN as a regex.

**`-i, --ignore-case`** — case-insensitive match.

**`--include`** — comma-separated file globs to include.  
Default: `*.py`, `*.md`, `*.rst`, `*.yaml`, `*.yml`, `*.launch.py`, `*.txt`  
*#example:* `--include "*.py,*.launch.py,*.md"`

**`--exclude`** — comma-separated globs to exclude.  
Default excludes: `*.min.js`, `*.lock`, `*.bin`, `*.exe`, `*.dll`, `*.so`, `*.dylib`

**`--exclude-dirs`** — directory names to skip (repeatable).  
Default: `.git`, `.vscode`, `node_modules`, `__pycache__`, etc.

**`--max-file-bytes`** — cap bytes read per file (default ~2.5MB).

**`-C, --context`** — lines of context around each hit (default: 2).

**`--per-file-limit`** — max snippets per file (default: 20).

**`--total-limit`** — max snippets overall (default: 500).

**`--json`** — emit JSON for tool consumption.

## Examples

```bash
# Pipe candidate directories from focus_tree, then grep for teleop-ish clues
python focus_tree.py spot -b ./bdai-main --must-parent src --paths-only \
| python focus_grep.py "(teleop|wasd|rviz|launch)" --regex --stdin-paths -i -C 3 --json

# Search inside a subtree for teleop mentions in code/docs
python focus_grep.py "teleop" ./bdai-main/ws/src --include "*.py,*.launch.py,*.md" -i -C 2

# Docs-only search
python focus_grep.py "graphnav" ./bdai-main --include "*.md,*.rst" -i --json
```

**PowerShell version** (no trailing backslash; use backtick for continuation):

```powershell
python focus_tree.py spot -b ./bdai-main --must-parent src --paths-only `
| python focus_grep.py "(teleop|wasd|rviz|launch)" --regex --stdin-paths -i -C 3 --json
```

## JSON output shape

```json
{
  "pattern": "(teleop|wasd|rviz|launch)",
  "regex": true,
  "case_insensitive": true,
  "total_snippets": 7,
  "results": [
    {
      "path": "C:/tests/bdai-main/ws/src/.../spot_rviz_teleop.launch.py",
      "hits": 3,
      "snippets": [
        {
          "line": 42,
          "start": 40,
          "end": 44,
          "context": [
            {"line": 40, "text": "..."},
            {"line": 41, "text": "..."},
            {"line": 42, "text": "ros2 launch spot_rviz_teleop.launch.py ..."},
            {"line": 43, "text": "..."},
            {"line": 44, "text": "..."}
          ]
        }
      ]
    }
  ]
}
```

Use this JSON to let your orchestrator/LLM pick which files/lines to read deeply next.

## Exit codes

- **0** — success (may be zero hits but valid run)
- **2** — usage error / no valid input paths

## Tips

- Narrow noise by combining globs and dir excludes.
- Keep `--total-limit` modest (e.g., 200) so the LLM isn't flooded.
- For CI/tests, pin `--json` and snapshot results for regression diffs.

## Troubleshooting

**PowerShell pipeline error with "\\":**  
In PowerShell, `\` is not a line continuation. Remove it or use backtick `` ` ``.

**"No valid input paths":**  
Provide at least one path or `--stdin-paths` with piped input.

## Pairing with focus_tree

This is the golden flow:

```powershell
# Win/PowerShell
python focus_tree.py spot -b ./bdai-main --must-parent src --paths-only `
| python focus_grep.py "(teleop|wasd|rviz|launch)" --regex --stdin-paths -i -C 3 --json
```

```bash
# mac/linux
python focus_tree.py spot -b ./bdai-main --must-parent src --paths-only \
| python focus_grep.py "(teleop|wasd|rviz|launch)" --regex --stdin-paths -i -C 3 --json
```

You now have a cheap, deterministic scout that an LLM can drive:

1. **focus_tree** → pick neighborhoods
2. **focus_grep** → surface candidate lines
3. **(optional) peek/read** → bounded reads on top files
4. **Answer** (RAG only as fallback)