# focus_tree

A tiny CLI to find and preview high-value directories before you hand anything to an LLM or a RAG step. It scans one or more base paths, matches directory names by keyword/aliases (e.g., `spot` → `spot_ros2`), lets you filter by parent components (e.g., must include `src`), and prints a bounded ASCII tree or just absolute paths.

## Install

Just drop `focus_tree.py` anywhere on your PATH (or call with `python focus_tree.py …`).  
Python 3.9+ recommended.

```bash
# optional: make it executable on mac/linux
chmod +x focus_tree.py
```

## Usage

```bash
python focus_tree.py KEYWORD -b BASE [-b BASE ...]
                             [--depth N] [--limit N] [--exclude NAME ...]
                             [--must-parent CSV|--must-parent NAME ...]
                             [--must-parent-all CSV|--must-parent-all NAME ...]
                             [--not-parent CSV|--not-parent NAME ...]
                             [--must-contain CSV] [--contain-depth N]
                             [--paths-only]
                             [--name-exact CSV] [--name-regex REGEX ...]
```

## Arguments

**`KEYWORD`** — directory keyword/alias (e.g., `spot`, `ros`, `amp`, `bdai`).  
Aliases are configurable in `ALIAS_MAP`.

**`-b, --base`** — one or more base paths to search.

**`--depth`** — max tree depth when printing (default: 2).

**`--limit`** — max total entries printed per tree (default: 200).

**`--exclude`** — directory names to skip (repeatable). Defaults include `.git`, `node_modules`, etc.

**`--must-parent`** — path must contain ANY of these parent components.  
*#example:* `--must-parent src` or `--must-parent src,ws`

**`--must-parent-all`** — path must contain ALL components.  
*#example:* `--must-parent-all ws,src`

**`--not-parent`** — exclude any path that contains these components.  
*#example:* `--not-parent tests,examples`

**`--must-contain`** — matched directory must contain any filename/extension within a bounded depth.  
Supports extensions like `.rst`/`.md`.  
*#example:* `--must-contain index.rst,conf.py` (pair with `--contain-depth 2`)

**`--contain-depth`** — depth bound for `--must-contain` relative scan (default: 1).

**`--paths-only`** — print absolute paths only (one per line), no tree.

**`--name-exact`** — only match directories whose name equals one of these.  
*#example:* `--name-exact doc,docs`

**`--name-regex`** — only match directories whose name matches any regex (case-insensitive).  
*#example:* `--name-regex "spot_.*_driver"`

## Examples

```bash
# Bash / Zsh
python focus_tree.py spot -b ./bdai-main --must-parent src

# Only doc roots inside src that look like Sphinx docs
python focus_tree.py docs -b ./bdai-main --must-parent src \
  --must-contain index.rst,conf.py --contain-depth 2

# Exact folder names
python focus_tree.py docs -b ./bdai-main --must-parent src --name-exact doc,docs

# Regex on folder names
python focus_tree.py spot -b ./bdai-main --name-regex "spot_.*_driver"

# Paths only (for piping)
python focus_tree.py spot -b ./bdai-main --must-parent src --paths-only
```

**PowerShell note:** use a backtick `` ` `` for line continuation (not `\`) or just write on one line.

```powershell
# PowerShell pipeline (note the lack of trailing backslash)
python focus_tree.py spot -b ./bdai-main --must-parent src --paths-only `
| python focus_grep.py "(teleop|wasd|rviz|launch)" --regex --stdin-paths -i -C 3 --json
```

## Exit codes

- **0** — success, at least one match printed
- **1** — no matches
- **2** — argument/usage error

## Tips

- Start broad (`spot`), then add `--must-parent src` and `--name-regex` to sharpen.
- Use `--paths-only` to feed later tools (`focus_grep.py`, your LLM "peek/read" tool).
- Tune `ALIAS_MAP` for your org names (AMP/BDAI/etc.).

## Roadmap (optional)

- `--format json` output (with path + tree text)
- Pre-baked "profiles" (e.g., `--profile ros2-teleop`) that inject common filters