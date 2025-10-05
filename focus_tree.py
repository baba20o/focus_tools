#!/usr/bin/env python3
# file: focus_tree.py
from pathlib import Path
from typing import Iterable, List, Dict
import os
import sys
import argparse

# --- Config knobs (tweak freely) ---
DEFAULT_EXCLUDES = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__",
    "build", "dist", ".venv", "venv", ".mypy_cache", ".pytest_cache"
}
DEFAULT_MAX_DEPTH = 2
DEFAULT_MAX_ENTRIES = 200

# Optional alias map so "spot" can match "spot_ros2", etc.
ALIAS_MAP = {
    "spot": ["spot_ros2", "spot-sdk", "spot_robot"],
    "ros": ["ros", "ros2", "ros_ws", "catkin_ws"],
    "amp": ["amp"],
    "bdai": ["bdai", "bdai-main", "bdai_core"],
}

# ---------------- basic utils ---------------- #

def normalize(s: str) -> str:
    return s.strip().lower().replace("-", "_")

def generate_aliases(keyword: str) -> List[str]:
    k = normalize(keyword)
    aliases = set([k])
    for key, vals in ALIAS_MAP.items():
        if k == key or k in map(normalize, vals):
            aliases.add(key)
            aliases.update(map(normalize, vals))
    return list(aliases)

def dir_matches(name: str, aliases: List[str]) -> bool:
    n = normalize(name)
    # simple contains or exact token match
    return any(a in n or n in a for a in aliases)

def any_parent(path: Path, parents: List[str]) -> bool:
    if not parents:
        return True
    comps = [normalize(p) for p in path.parts]
    needles = [normalize(x) for x in parents]
    return any(any(n in c or c in n for n in needles) for c in comps)

def all_parents(path: Path, parents: List[str]) -> bool:
    if not parents:
        return True
    comps = [normalize(p) for p in path.parts]
    def present(n: str) -> bool:
        return any(n in c or c in n for c in comps)
    return all(present(normalize(n)) for n in parents)

def none_parent(path: Path, parents: List[str]) -> bool:
    """True iff none of the banned parents appear in path components."""
    if not parents:
        return True
    comps = [normalize(p) for p in path.parts]
    needles = [normalize(x) for x in parents]
    return all(not (n in c or c in n) for c in comps for n in needles)

def parse_list(raw: List[str] | None) -> List[str]:
    """Accept repeated flags or comma-separated list and flatten."""
    if not raw:
        return []
    out: List[str] = []
    for item in raw:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        out.extend(parts)
    return out

def dir_contains_any(path: Path, names: List[str], max_depth: int, excludes_norm: set[str]) -> bool:
    """
    Return True if any of 'names' (case-insensitive filename or extension like '.rst') exists
    within 'path' up to 'max_depth' levels (relative to path), skipping excludes.
    """
    if not names:
        return True
    targets = [normalize(n) for n in names]

    root_depth = len(path.parts)
    for r, dirs, files in os.walk(path):
        # depth bound
        depth = len(Path(r).parts) - root_depth
        if depth > max_depth:
            # prune deeper walk
            dirs[:] = []
            continue
        # prune excluded dirs
        dirs[:] = [d for d in dirs if normalize(d) not in excludes_norm]
        # check files
        for f in files:
            fn = normalize(f)
            # allow filename or extension match
            for t in targets:
                if t.startswith("."):
                    if fn.endswith(t):
                        return True
                if t in fn or fn in t:
                    return True
    return False

# ---------------- tree builder ---------------- #

def build_tree(root: Path,
               max_depth: int = DEFAULT_MAX_DEPTH,
               max_entries: int = DEFAULT_MAX_ENTRIES,
               excludes: Iterable[str] = DEFAULT_EXCLUDES) -> str:
    """
    Return a bounded ASCII tree for 'root'.
    """
    excludes_norm = {normalize(e) for e in excludes}
    lines: List[str] = [str(root.resolve())]

    def _listdir(p: Path) -> List[Path]:
        try:
            items = list(p.iterdir())
        except Exception:
            return []
        items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
        return items

    def _tree(p: Path, prefix: str, depth: int, budget: List[int]):
        if depth <= 0 or budget[0] <= 0:
            return
        items = [c for c in _listdir(p) if normalize(c.name) not in excludes_norm]
        shown = 0
        for i, child in enumerate(items):
            if budget[0] <= 0:
                break
            connector = "└── " if i == len(items) - 1 else "├── "
            lines.append(f"{prefix}{connector}{child.name}")
            budget[0] -= 1
            shown += 1
            if child.is_dir():
                extension = "    " if i == len(items) - 1 else "│   "
                _tree(child, prefix + extension, depth - 1, budget)
        remaining = len(items) - shown
        if remaining > 0 and budget[0] <= 0:
            lines.append(f"{prefix}… (+{remaining} more)")

    _tree(root, "", max_depth, [max_entries])
    return "\n".join(lines)

# ---------------- finder ---------------- #

def find_matching_dirs(keyword: str,
                       base_paths: Iterable[Path],
                       max_depth: int = DEFAULT_MAX_DEPTH,
                       max_entries: int = DEFAULT_MAX_ENTRIES,
                       excludes: Iterable[str] = DEFAULT_EXCLUDES,
                       must_parent_any: List[str] | None = None,
                       must_parent_all: List[str] | None = None,
                       not_parent: List[str] | None = None,
                       must_contain: List[str] | None = None,
                       contain_depth: int = 1,
                       paths_only: bool = False) -> Dict[Path, str]:
    """
    Search base_paths for directories whose names match the keyword (with aliases).
    Filters:
      - must_parent_any: path must include ANY of these components
      - must_parent_all: path must include ALL of these components
      - not_parent: path must include NONE of these components
      - must_contain: directory must contain any of these filenames/exts within 'contain_depth'

    Return {matched_dir_path: tree_string or "" if paths_only}.
    """
    aliases = generate_aliases(keyword)
    matches: List[Path] = []
    excludes_norm = {normalize(x) for x in excludes}
    must_parent_any = must_parent_any or []
    must_parent_all = must_parent_all or []
    not_parent = not_parent or []
    must_contain = must_contain or []

    for base in base_paths:
        base = base.expanduser().resolve()
        if not base.exists():
            continue
        for root, dirs, _files in os.walk(base):
            dirs[:] = [d for d in dirs if normalize(d) not in excludes_norm]
            for d in dirs:
                if dir_matches(d, aliases):
                    candidate = Path(root) / d
                    if not any_parent(candidate, must_parent_any):
                        continue
                    if not all_parents(candidate, must_parent_all):
                        continue
                    if not none_parent(candidate, not_parent):
                        continue
                    if not dir_contains_any(candidate, must_contain, contain_depth, excludes_norm):
                        continue
                    matches.append(candidate)

    uniq: List[Path] = sorted(set(matches), key=lambda p: str(p).lower())

    output: Dict[Path, str] = {}
    for m in uniq:
        output[m] = "" if paths_only else build_tree(m, max_depth=max_depth, max_entries=max_entries, excludes=excludes)
    return output

# ---------------- CLI ---------------- #

def main():
    parser = argparse.ArgumentParser(description="Find directories matching a keyword and print a bounded file tree.")
    parser.add_argument("keyword", help="Keyword or alias (e.g., ROS, AMP, BDAI, spot)")
    parser.add_argument("-b", "--base", action="append", required=True,
                        help="Base path to search (can repeat). Example: -b ./repos -b ~/work")
    parser.add_argument("--depth", type=int, default=DEFAULT_MAX_DEPTH, help="Max directory depth to print (default: 2)")
    parser.add_argument("--limit", type=int, default=DEFAULT_MAX_ENTRIES, help="Max entries to print across the tree (default: 200)")
    parser.add_argument("--exclude", action="append", default=list(DEFAULT_EXCLUDES),
                        help="Directory names to exclude (can repeat)")

    # Filters
    parser.add_argument("--must-parent", action="append",
                        help="Path must contain ANY of these parent components (repeat or CSV) "
                             "#example: --must-parent src  |  --must-parent src,ws")
    parser.add_argument("--must-parent-all", action="append",
                        help="Path must contain ALL of these parent components (repeat or CSV) "
                             "#example: --must-parent-all ws --must-parent-all src  |  --must-parent-all ws,src")
    parser.add_argument("--not-parent", action="append",
                        help="Exclude paths that contain ANY of these components "
                             "#example: --not-parent tests,examples,rviz")

    parser.add_argument("--must-contain", action="append",
                        help="Directory must contain any of these filenames or extensions within contain-depth "
                             "(extensions like .rst or .md supported) "
                             "#example: --must-contain README.md,index.rst  |  --must-contain .rst")
    parser.add_argument("--contain-depth", type=int, default=1,
                        help="Depth bound for --must-contain scan relative to matched dir (default: 1) "
                             "#example: --contain-depth 2")

    parser.add_argument("--paths-only", action="store_true",
                        help="Print only absolute paths to matched directories (one per line) "
                             "#example: --paths-only")

    args = parser.parse_args()

    bases = [Path(p) for p in args.base]

    # Warn on missing bases & show resolved paths
    resolved = []
    missing = []
    for b in bases:
        rb = b.expanduser().resolve()
        resolved.append(rb)
        if not rb.exists():
            missing.append(str(rb))
    if missing:
        print("Warning: these base paths do not exist:")
        for m in missing:
            print(f"  - {m}")

    must_parent_any = parse_list(args.must_parent)
    must_parent_all = parse_list(args.must_parent_all)
    not_parent = parse_list(args.not_parent)
    must_contain = parse_list(args.must_contain)

    results = find_matching_dirs(
        keyword=args.keyword,
        base_paths=resolved,
        max_depth=args.depth,
        max_entries=args.limit,
        excludes=args.exclude,
        must_parent_any=must_parent_any,
        must_parent_all=must_parent_all,
        not_parent=not_parent,
        must_contain=must_contain,
        contain_depth=args.contain_depth,
        paths_only=args.paths_only,
    )

    if not results:
        shown_bases = ", ".join(str(b) for b in resolved)
        extra = []
        if must_parent_any: extra.append(f"must-parent={must_parent_any}")
        if must_parent_all: extra.append(f"must-parent-all={must_parent_all}")
        if not_parent: extra.append(f"not-parent={not_parent}")
        if must_contain: extra.append(f"must-contain={must_contain} (depth={args.contain_depth})")
        filt = " with " + "; ".join(extra) if extra else ""
        print(f"No matching directories found for '{args.keyword}'{filt} under: {shown_bases}")
        sys.exit(1)

    if args.paths_only:
        for path in results.keys():
            print(str(path.resolve()))
        return

    first = True
    for path, tree in results.items():
        if not first:
            print("\n" + "=" * 80 + "\n")
        first = False
        print(tree)

if __name__ == "__main__":
    main()
