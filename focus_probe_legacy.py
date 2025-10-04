#!/usr/bin/env python3
# file: focus_probe.py
"""
One-shot probe for repo questions:
  1) Find candidate directories by KEYWORD (+ parent/path filters)
  2) Grep inside candidate dirs for a PATTERN (regex or literal) with file globs
  3) Rank hits and pick top-N files
  4) Return JSON with contextual snippets and optional head/tail peek or bounded read

Usage examples (PowerShell-friendly):
  # Spot teleop scout: scope to src, grep teleop-y terms, return top 8 files with context
  python focus_probe.py spot "(teleop|wasd|rviz|launch)" -b ./bdai-main --must-parent src `
      --include "*.py,*.launch.py,*.md" --regex -i --top-files 8 --peek --json

  # Docs-centric probe
  python focus_probe.py docs "teleop" -b ./bdai-main --must-parent src `
      --include "*.md,*.rst" -i --top-files 5 --peek --json
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Iterable, Iterator, Tuple, Optional
import os, sys, re, argparse, json, fnmatch, base64

# ----------------------- defaults / knobs -----------------------
DEFAULT_EXCLUDES_DIR = {".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__"}
DEFAULT_INCLUDE_GLOBS = ["*.py", "*.pyw", "*.md", "*.rst", "*.yaml", "*.yml", "*.launch.py", "*.txt"]
DEFAULT_EXCLUDE_GLOBS = ["*.min.js", "*.lock", "*.bin", "*.exe", "*.dll", "*.so", "*.dylib"]
DEFAULT_MAX_FILE_BYTES = 2_500_000  # ~2.5MB scan cap per file (safety)
DEFAULT_CONTEXT = 2
DEFAULT_PER_FILE_SNIPPETS = 6
DEFAULT_TOTAL_SNIPPETS = 300
DEFAULT_MAX_DEPTH_TREE = 2
DEFAULT_MAX_ENTRIES_TREE = 200
DEFAULT_TOP_FILES = 8

ALIAS_MAP = {
    "spot": ["spot_ros2", "spot-sdk", "spot_robot"],
    "ros" : ["ros", "ros2", "ros_ws", "catkin_ws"],
    "amp" : ["amp"],
    "bdai": ["bdai", "bdai-main", "bdai_core"],
}

# ----------------------- helpers -----------------------
def normalize(s: str) -> str:
    return s.strip().lower().replace("-", "_")

def parse_csv_list(raw: List[str] | None) -> List[str]:
    if not raw: return []
    out: List[str] = []
    for item in raw:
        out.extend([p.strip() for p in item.split(",") if p.strip()])
    return out

def generate_aliases(keyword: str) -> List[str]:
    k = normalize(keyword)
    aliases = set([k])
    for key, vals in ALIAS_MAP.items():
        if k == key or k in map(normalize, vals):
            aliases.add(key)
            aliases.update(map(normalize, vals))
    return list(aliases)

def dir_name_matches(name: str, aliases: List[str], name_exact: List[str], name_regexes: List[str]) -> bool:
    n = normalize(name)
    # name_exact gate (if provided)
    if name_exact:
        if not any(n == normalize(x) for x in name_exact):
            return False
    # name_regex gate (if provided)
    if name_regexes:
        ok = False
        for rx in name_regexes:
            try:
                if re.search(rx, name, re.IGNORECASE):
                    ok = True; break
            except re.error:
                continue
        if not ok:
            return False
    # alias fuzzy match (always applied)
    return any(a in n or n in a for a in aliases)

def path_has_any(path: Path, parents: List[str]) -> bool:
    if not parents: return True
    comps = [normalize(p) for p in path.parts]
    needles = [normalize(x) for x in parents]
    return any(any(n in c or c in n for n in needles) for c in comps)

def path_has_all(path: Path, parents: List[str]) -> bool:
    if not parents: return True
    comps = [normalize(p) for p in path.parts]
    def present(n: str) -> bool: return any(n in c or c in n for c in comps)
    return all(present(normalize(n)) for n in parents)

def path_has_none(path: Path, parents: List[str]) -> bool:
    if not parents: return True
    comps = [normalize(p) for p in path.parts]
    needles = [normalize(x) for x in parents]
    return all(not (n in c or c in n) for c in comps for n in needles)

def is_probably_binary(head: bytes) -> bool:
    if b"\x00" in head: return True
    textish = sum(32 <= b <= 126 or b in (9,10,13) for b in head[:1024])
    return textish < 0.85 * min(1024, len(head))

def read_text_bounded(path: Path, max_bytes: int) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            buf = f.read(max_bytes + 1)
        if is_probably_binary(buf):
            return None
        return buf[:max_bytes].decode("utf-8", errors="ignore")
    except Exception:
        return None

def listdir_sorted(p: Path) -> List[Path]:
    try:
        items = list(p.iterdir())
    except Exception:
        return []
    items.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
    return items

# ----------------------- stage 1: find candidate dirs -----------------------
def find_dirs(keyword: str,
              bases: List[Path],
              excludes_dir: Iterable[str],
              must_parent_any: List[str],
              must_parent_all: List[str],
              not_parent: List[str],
              name_exact: List[str],
              name_regex: List[str]) -> List[Path]:
    aliases = generate_aliases(keyword)
    ex_norm = {normalize(d) for d in excludes_dir}
    hits: List[Path] = []
    for base in bases:
        b = base.expanduser().resolve()
        if not b.exists(): continue
        for root, dirs, _files in os.walk(b):
            # prune
            dirs[:] = [d for d in dirs if normalize(d) not in ex_norm]
            for d in dirs:
                if not dir_name_matches(d, aliases, name_exact, name_regex): continue
                cand = Path(root) / d
                if not path_has_any(cand, must_parent_any): continue
                if not path_has_all(cand, must_parent_all): continue
                if not path_has_none(cand, not_parent): continue
                hits.append(cand)
    # de-dup, stable sort
    return sorted(set(hits), key=lambda p: str(p).lower())

def build_ascii_tree(root: Path, max_depth: int, max_entries: int, excludes_dir: Iterable[str]) -> str:
    ex_norm = {normalize(d) for d in excludes_dir}
    lines: List[str] = [str(root.resolve())]
    def _tree(p: Path, prefix: str, depth: int, budget: List[int]):
        if depth <= 0 or budget[0] <= 0: return
        items = [c for c in listdir_sorted(p) if normalize(c.name) not in ex_norm]
        shown = 0
        for i, child in enumerate(items):
            if budget[0] <= 0: break
            connector = "└── " if i == len(items)-1 else "├── "
            lines.append(f"{prefix}{connector}{child.name}")
            budget[0] -= 1; shown += 1
            if child.is_dir():
                ext = "    " if i == len(items)-1 else "│   "
                _tree(child, prefix+ext, depth-1, budget)
        rem = len(items) - shown
        if rem > 0 and budget[0] <= 0:
            lines.append(f"{prefix}… (+{rem} more)")
    _tree(root, "", max_depth, [max_entries])
    return "\n".join(lines)

# ----------------------- stage 2: grep inside those dirs -----------------------
def should_consider_file(path: Path, includes: List[str], excludes: List[str]) -> bool:
    name = path.name
    if includes and not any(fnmatch.fnmatch(name, g) for g in includes): return False
    if any(fnmatch.fnmatch(name, g) for g in excludes): return False
    return True

def iter_files(root: Path, includes: List[str], excludes: List[str], exclude_dirs: Iterable[str]) -> Iterator[Path]:
    ex_dirs_norm = {normalize(d) for d in exclude_dirs}
    for r, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if normalize(d) not in ex_dirs_norm]
        for f in files:
            p = Path(r) / f
            if should_consider_file(p, includes, excludes):
                yield p

def grep_lines(text: str, pattern: str, regex: bool, ignore_case: bool) -> List[Tuple[int,str]]:
    lines = text.splitlines(True)
    hits: List[Tuple[int,str]] = []
    flags = re.IGNORECASE if ignore_case else 0
    if regex:
        rx = re.compile(pattern, flags)
        for i, ln in enumerate(lines, 1):
            if rx.search(ln): hits.append((i, ln.rstrip("\n")))
    else:
        needle = pattern.lower() if ignore_case else pattern
        for i, ln in enumerate(lines, 1):
            hay = ln.lower() if ignore_case else ln
            if needle in hay: hits.append((i, ln.rstrip("\n")))
    return hits

def make_snippets(full_lines: List[str], hit_lines: List[Tuple[int,str]], context: int, per_file_limit: int) -> List[Dict]:
    out: List[Dict] = []
    n = len(full_lines); used = 0
    for ln, _ in hit_lines:
        if used >= per_file_limit: break
        start = max(1, ln-context)
        end   = min(n, ln+context)
        block = [{"line": i, "text": full_lines[i-1].rstrip("\n")} for i in range(start, end+1)]
        out.append({"line": ln, "start": start, "end": end, "context": block})
        used += 1
    return out

def probe_dirs_grep(dirs: List[Path],
                    pattern: str,
                    regex: bool,
                    ignore_case: bool,
                    includes: List[str],
                    excludes: List[str],
                    exclude_dirs: Iterable[str],
                    max_file_bytes: int,
                    context: int,
                    per_file_snippets: int,
                    total_snippets: int) -> List[Dict]:
    results: List[Dict] = []
    total = 0
    for d in dirs:
        # Gather candidate files
        files = list(iter_files(d, includes, excludes, exclude_dirs))
        for f in files:
            if total >= total_snippets: break
            txt = read_text_bounded(f, max_file_bytes)
            if txt is None: continue
            hits = grep_lines(txt, pattern, regex, ignore_case)
            if not hits: continue
            lines = txt.splitlines()
            snippets = make_snippets(lines, hits, context, per_file_snippets)
            total += len(snippets)
            results.append({
                "path": str(f),
                "dir": str(d),
                "hits": len(hits),
                "snippets": snippets
            })
            if total >= total_snippets: break
    return results

# ----------------------- ranking & peek/read -----------------------
def rank_results(results: List[Dict]) -> List[Dict]:
    # Score = total hits + small bonus for more snippets
    scored = []
    for r in results:
        score = r["hits"] + 0.1*len(r["snippets"])
        scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _s, r in scored]

def peek_file(path: Path, head_lines: int = 80, tail_lines: int = 40, max_bytes: int = 200_000) -> Dict:
    txt = read_text_bounded(path, max_bytes) or ""
    lines = txt.splitlines()
    head = lines[:head_lines]
    tail = lines[-tail_lines:] if len(lines) > head_lines else []
    return {"head": head, "tail": tail, "total_lines": len(lines), "truncated_bytes": max(0, 0)}

def bounded_read(path: Path, byte_budget: int = 12_000) -> str:
    txt = read_text_bounded(path, byte_budget) or ""
    return txt

# ----------------------- CLI -----------------------
def main():
    ap = argparse.ArgumentParser(description="focus_probe: tree → grep → rank → peek/read → JSON bundle")
    ap.add_argument("keyword", help="Directory keyword/alias (e.g., spot, ros, amp, bdai)")
    ap.add_argument("pattern", help="Search pattern (regex if --regex) used during grep stage")
    ap.add_argument("-b", "--base", action="append", required=True,
                    help="Base path(s) to search. Repeatable. #example: -b ./bdai-main -b ~/code")

    # Tree filters
    ap.add_argument("--must-parent", action="append", help="#example: --must-parent src,ws")
    ap.add_argument("--must-parent-all", action="append", help="#example: --must-parent-all ws,src")
    ap.add_argument("--not-parent", action="append", help="#example: --not-parent tests,examples,build")
    ap.add_argument("--name-exact", action="append", help="#example: --name-exact doc,docs")
    ap.add_argument("--name-regex", action="append", help="#example: --name-regex 'spot_.*_driver'")

    # Grep controls
    ap.add_argument("--regex", action="store_true", help="Treat PATTERN as regular expression")
    ap.add_argument("-i", "--ignore-case", action="store_true", help="Case-insensitive match")
    ap.add_argument("--include", action="append",
                    help="Comma-separated file globs to include. "
                         f"Default: {','.join(DEFAULT_INCLUDE_GLOBS)}")
    ap.add_argument("--exclude", action="append",
                    help="Comma-separated file globs to exclude. "
                         f"Default: {','.join(DEFAULT_EXCLUDE_GLOBS)}")
    ap.add_argument("--exclude-dirs", action="append", default=list(DEFAULT_EXCLUDES_DIR),
                    help="Directory names to exclude recursively")

    # Limits
    ap.add_argument("--context", type=int, default=DEFAULT_CONTEXT, help=f"Context lines around hits (default {DEFAULT_CONTEXT})")
    ap.add_argument("--per-file-snippets", type=int, default=DEFAULT_PER_FILE_SNIPPETS, help=f"Max snippets per file (default {DEFAULT_PER_FILE_SNIPPETS})")
    ap.add_argument("--total-snippets", type=int, default=DEFAULT_TOTAL_SNIPPETS, help=f"Max snippets overall (default {DEFAULT_TOTAL_SNIPPETS})")
    ap.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES, help=f"Max bytes to scan per file (default {DEFAULT_MAX_FILE_BYTES})")
    ap.add_argument("--top-files", type=int, default=DEFAULT_TOP_FILES, help=f"How many top files to include in the bundle (default {DEFAULT_TOP_FILES})")

    # Output enrichments
    ap.add_argument("--ascii-tree", action="store_true", help="Include an ASCII preview for each matched directory")
    ap.add_argument("--tree-depth", type=int, default=DEFAULT_MAX_DEPTH_TREE, help=f"ASCII tree depth (default {DEFAULT_MAX_DEPTH_TREE})")
    ap.add_argument("--tree-limit", type=int, default=DEFAULT_MAX_ENTRIES_TREE, help=f"ASCII tree entry cap (default {DEFAULT_MAX_ENTRIES_TREE})")
    ap.add_argument("--peek", action="store_true", help="Include head/tail preview for each top file")
    ap.add_argument("--read-bytes", type=int, default=0, help="If >0, attach bounded file content (byte budget) for each top file")

    ap.add_argument("--json", action="store_true", help="Emit JSON (recommended). If omitted, prints summary + JSON.")

    args = ap.parse_args()

    bases = [Path(b) for b in args.base]
    resolved, missing = [], []
    for b in bases:
        rb = b.expanduser().resolve()
        (resolved if rb.exists() else missing).append(rb)
    if missing:
        print("Warning: these base paths do not exist:")
        for m in missing: print(f"  - {m}")

    must_any   = parse_csv_list(args.must_parent)
    must_all   = parse_csv_list(args.must_parent_all)
    not_parent = parse_csv_list(args.not_parent)
    name_exact = parse_csv_list(args.name_exact)
    name_regex = parse_csv_list(args.name_regex)

    include_globs = parse_csv_list(args.include) or list(DEFAULT_INCLUDE_GLOBS)
    exclude_globs = parse_csv_list(args.exclude) or list(DEFAULT_EXCLUDE_GLOBS)
    exclude_dirs  = parse_csv_list(args.exclude_dirs) or list(DEFAULT_EXCLUDES_DIR)

    # Stage 1: directories
    cand_dirs = find_dirs(
        keyword=args.keyword,
        bases=resolved,
        excludes_dir=exclude_dirs,
        must_parent_any=must_any,
        must_parent_all=must_all,
        not_parent=not_parent,
        name_exact=name_exact,
        name_regex=name_regex
    )

    if not cand_dirs:
        out = {
            "keyword": args.keyword,
            "pattern": args.pattern,
            "dirs_found": 0,
            "bases": [str(b) for b in resolved],
            "message": "No candidate directories"
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(1)

    trees = {}
    if args.ascii_tree:
        for d in cand_dirs:
            trees[str(d)] = build_ascii_tree(d, args.tree_depth, args.tree_limit, exclude_dirs)

    # Stage 2: grep
    grep_results = probe_dirs_grep(
        dirs=cand_dirs,
        pattern=args.pattern,
        regex=args.regex,
        ignore_case=args.ignore_case,
        includes=include_globs,
        excludes=exclude_globs,
        exclude_dirs=exclude_dirs,
        max_file_bytes=args.max_file_bytes,
        context=args.context,
        per_file_snippets=args.per_file_snippets,
        total_snippets=args.total_snippets
    )

    if not grep_results:
        out = {
            "keyword": args.keyword,
            "pattern": args.pattern,
            "dirs_found": len(cand_dirs),
            "files_scanned": 0,
            "hits": 0,
            "trees": trees if args.ascii_tree else {},
            "message": "No grep hits"
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)

    ranked = rank_results(grep_results)
    top = ranked[: max(1, args.top_files)]

    # Optional enrichments on top files
    enriched = []
    for entry in top:
        p = Path(entry["path"])
        add: Dict = {"path": entry["path"], "dir": entry["dir"], "hits": entry["hits"], "snippets": entry["snippets"]}
        if args.peek:
            add["peek"] = peek_file(p)
        if args.read_bytes and args.read_bytes > 0:
            add["read"] = bounded_read(p, args.read_bytes)
        enriched.append(add)

    bundle = {
        "keyword": args.keyword,
        "pattern": args.pattern,
        "regex": args.regex,
        "ignore_case": args.ignore_case,
        "bases": [str(b) for b in resolved],
        "filters": {
            "must_parent_any": must_any,
            "must_parent_all": must_all,
            "not_parent": not_parent,
            "name_exact": name_exact,
            "name_regex": name_regex,
            "include_globs": include_globs,
            "exclude_globs": exclude_globs,
            "exclude_dirs": exclude_dirs
        },
        "dirs_found": len(cand_dirs),
        "trees": trees if args.ascii_tree else {},
        "hits_total_snippets": sum(len(e["snippets"]) for e in grep_results),
        "files_with_hits": len(grep_results),
        "top_files": enriched
    }

    if args.json:
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
    else:
        # brief summary then JSON (useful in terminal)
        print(f"[focus_probe] dirs={bundle['dirs_found']} files_with_hits={bundle['files_with_hits']} "
              f"snippets={bundle['hits_total_snippets']} top_files={len(enriched)}")
        print(json.dumps(bundle, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
