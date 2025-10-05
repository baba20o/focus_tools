focus_probe — README

focus_probe is a one-shot scout & snipe CLI that does:

Find candidate directories by keyword + filters

Grep inside them for your pattern (regex/literal) with file globs

Rank hits and pick top N files

Return a JSON bundle with context snippets, optional ASCII trees & file peeks

(New) Emit unique directory prefixes so your RAG can scope retrieval cleanly

It’s the “Laser-Blaster” you can hand to an LLM before any RAG.

Install

Just run it with Python 3.9+ (no external deps):

chmod +x focus_probe.py   # mac/linux optional

Usage
python focus_probe.py KEYWORD PATTERN -b BASE [-b BASE ...]
  [--must-parent CSV] [--must-parent-all CSV] [--not-parent CSV]
  [--name-exact CSV] [--name-regex REGEX ...]
  [--regex] [-i|--ignore-case]
  [--include CSV] [--exclude CSV] [--exclude-dirs NAME ...]
  [--context N] [--per-file-snippets N] [--total-snippets N]
  [--max-file-bytes N] [--top-files N]
  [--ascii-tree] [--tree-depth N] [--tree-limit N]
  [--peek] [--read-bytes N]
  [--content-first] [--include-all]
  [--file-name-regex REGEX ...] [--file-name-globs CSV] [--filename-weight X]
  [--json]
  [--emit-path-prefixes] [--prefixes-only]

Key ideas

KEYWORD picks the neighborhoods (dirs). Aliases in ALIAS_MAP (e.g., spot → spot_ros2).

PATTERN pulls the evidence inside those dirs.

Globs & dir filters keep it cheap and focused.

Prefixes let you feed RAG path filters directly.

Important flags

Tree narrowing:

--must-parent src (ANY), --must-parent-all ws,src (ALL), --not-parent tests,examples

--name-exact doc,docs, --name-regex "spot_.*_driver"

Grep control:

--regex, -i (ignore case)

--include "*.py,*.launch.py,*.md", --exclude "*.min.js,*.lock"

--context 3, --per-file-snippets 6, --total-snippets 300

Breadth and authority:

--content-first           Search entire base(s) without directory-name gate (cluster after)

--include-all             Do not limit by include globs (search all file types)

--file-name-regex         Promote files whose NAMES match (authority channel)

--file-name-globs         Promote files whose NAMES match globs (e.g., robot_actions.py)

--filename-weight X       Multiplier applied to filename matches (default 2.0)

Output:

--ascii-tree + --tree-depth/--tree-limit

--peek (head/tail preview), --read-bytes 12000 (bounded content)

--json (recommended for tools)

--emit-path-prefixes (prints one-per-line after JSON)

--prefixes-only (prints prefixes only; no JSON)

Examples
1) Teleop scout (code+docs) with JSON bundle
python focus_probe.py spot "(teleop|wasd|rviz|launch)" -b ./bdai-main --must-parent src `
  --include "*.py,*.launch.py,*.md" --regex -i --top-files 8 --peek --json

2) Docs-centric in code-adjacent dirs
python focus_probe.py docs "(index\\.rst|conf\\.py|teleop)" -b ./bdai-main --must-parent src `
  --include "*.md,*.rst" --regex -i --top-files 6 --ascii-tree --json

3) Driver investigation, avoid noise
python focus_probe.py spot "driver|node|bringup" -b ./bdai-main `
  --name-regex "spot_.*_driver" --not-parent tests,examples `
  --include "*.py,*.md,*.launch.py" --regex -i --top-files 10 --peek --json

4) Get only path prefixes (feed to RAG)
python focus_probe.py spot "(teleop|wasd|rviz|launch)" -b ./bdai-main --must-parent src `
  --include "*.py,*.launch.py,*.md" --regex -i --top-files 12 --prefixes-only

5) JSON + plain prefixes for a pipeline
# JSON to a file, prefixes to the console:
python focus_probe.py spot "(teleop|wasd|rviz|launch)" -b ./bdai-main --must-parent src `
  --include "*.py,*.launch.py,*.md" --regex -i --top-files 8 --json --emit-path-prefixes `
  > probe.json

Output format (JSON)
{
  "keyword": "spot",
  "pattern": "(teleop|wasd|rviz|launch)",
  "regex": true,
  "ignore_case": true,
  "bases": ["C:/tests/bdai-main"],
  "filters": { "...": "..." },
  "dirs_found": 7,
  "trees": { "...": "ASCII tree if requested" },
 "hits_total_snippets": 42,
 "files_with_hits": 15,
 "top_files": [
   {
     "path": "C:/tests/bdai-main/ws/src/.../spot_rviz_teleop.launch.py",
     "dir": "C:/tests/bdai-main/ws/src/.../spot_utilities/launch",
     "hits": 3,
     "snippets": [{ "line": 42, "start": 40, "end": 44, "context": [ ... ] }],
      "peek": { "head": [...], "tail": [...], "total_lines": 120 }    // if --peek
      "extracted_msg_fields": ["std_msgs/Header header", "float32 time_step", ...], // if .msg
      "extracted_urdf_joints": ["RJ1","RJ2", ...],                                 // if .urdf/.xacro
      // "read": "..."                                                // if --read-bytes > 0
    }
  ],
  "path_prefixes": [
    "C:/tests/bdai-main/ws/src/.../spot_utilities/launch",
    "C:/tests/bdai-main/ws/src/.../spot_utilities/examples"
  ]
}

Exit codes

0 success (even if zero hits, unless --prefixes-only and no prefixes)

1 no candidate dirs or (in --prefixes-only) no prefixes

2 argument/usage error

Tips

Keep --top-files modest (8–12) and use --path_prefixes to scope your RAG.

For the LLM: give it a short “tool card” explaining the knobs it can tune.

Pair with your RAG path filter: pass path_prefixes as path_prefixes=[...] to force focused retrieval.

Peek defaults

- Head: 400 lines, Tail: 80 lines by default (configurable). Peeks are powered by focus_read for bounded, binary‑safe reads.
