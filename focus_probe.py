#!/usr/bin/env python3
# file: focus_probe.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Iterable, Tuple, Optional
import argparse
import os
import re
import sys
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import fnmatch

import focus_common as fc

# Optional bounded reader integration
try:
    import focus_read as _focus_read
    _HAVE_FOCUS_READ = True
except Exception:
    _HAVE_FOCUS_READ = False

# ---------------- Defaults / Guards ----------------

DEFAULT_EXCLUDES_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__",
    "build", "dist", ".venv", "venv", ".mypy_cache", ".pytest_cache"
}
DEFAULT_INCLUDE_GLOBS = ["*.py", "*.md", "*.rst", "*.yaml", "*.yml", "*.launch.py", "*.txt"]
DEFAULT_EXCLUDE_GLOBS = ["*.min.js", "*.lock", "*.bin", "*.exe", "*.dll", "*.so", "*.dylib"]
DEFAULT_MAX_FILE_BYTES = 2_500_000
DEFAULT_CONTEXT = 2
DEFAULT_PER_FILE_LIMIT = 20
DEFAULT_TOTAL_LIMIT = 500
DEFAULT_TOP_FILES = 8

# ---------------- Small helpers ----------------

def match_globs(name: str, globs: List[str]) -> bool:
    import fnmatch
    return any(fnmatch.fnmatch(name, g) for g in globs)

def is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            data = f.read(1024)
        if b"\x00" in data:
            return True
    except Exception:
        return True
    return False

def read_text_bounded(path: Path, max_bytes: int) -> Optional[str]:
    try:
        with path.open("rb") as f:
            data = f.read(max_bytes + 1)
        if b"\x00" in data:
            return None
        text = data.decode("utf-8", errors="replace")
        return text[:max_bytes]
    except Exception:
        return None

# ---------------- Lightweight extractors ----------------

def _extract_msg_fields(text: str) -> list[str]:
    fields: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        fields.append(s)
    return fields

def _extract_urdf_joints(text: str) -> list[str]:
    # Avoid strict XML parsing to handle xacro; use regex for joint name attributes
    import re as _re
    names = _re.findall(r'<\s*joint[^>]*name\s*=\s*"([^"]+)"', text, flags=_re.IGNORECASE)
    return names

def _parse_msg_types(text: str) -> list[str]:
    types: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        # type can be like 'pkg/Type name' or 'Type name'
        tok = s.split()[0]
        if '/' in tok:
            tok = tok.split('/')[-1]
        # basic filter for primitive types
        if tok.lower() in {"bool","int8","uint8","int16","uint16","int32","uint32","int64","uint64","float32","float64","string","time","duration"}:
            continue
        # arrays like Type[]
        tok = tok.replace('[]','').strip()
        if tok and tok not in types:
            types.append(tok)
    return types

def _find_msg_file(type_name: str, search_roots: list[Path]) -> Optional[Path]:
    cand = f"{type_name}.msg"
    for root in search_roots:
        try:
            for p in root.rglob(cand):
                return p
        except Exception:
            continue
    return None

def _extract_python_symbol_block(text: str, name: str, max_lines: int = 60) -> list[dict]:
    lines = text.splitlines()
    target = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith(f"def {name}"):
            target = i
            break
    if target is None:
        return []
    # naive block capture: next max_lines or until next top-level def/class
    out = []
    end = min(len(lines), target + max_lines)
    for j in range(target, end):
        out.append({"line": j+1, "text": lines[j]})
        s = lines[j].lstrip()
        if j > target and (s.startswith("def ") or s.startswith("class ")):
            break
    return out

def _extract_msg_nested(types: list[str], search_roots: list[Path], max_depth: int = 2, max_types: int = 20) -> dict:
    """Breadth-limited nested .msg extraction up to max_depth levels.
    Returns {type_name: [field, ...]}.
    """
    nested: dict[str, list[str]] = {}
    visited: set[str] = set()
    from collections import deque
    q = deque([(t, 1) for t in types[:max_types]])
    while q and len(visited) < max_types:
        t, depth = q.popleft()
        if t in visited:
            continue
        visited.add(t)
        msgp = _find_msg_file(t, search_roots)
        if not msgp:
            continue
        txt = ""
        try:
            txt = read_text_bounded(msgp, 20000) or ""
        except Exception:
            txt = ""
        if not txt:
            continue
        fields = _extract_msg_fields(txt)[:50]
        if fields:
            nested[t] = fields
        if depth < max_depth:
            sub_types = _parse_msg_types(txt)
            for st in sub_types:
                if st not in visited:
                    q.append((st, depth + 1))
    return nested

def grep_file(path: Path, pattern: str, regex: bool, ignore_case: bool,
              per_file_limit: int, context: int, max_file_bytes: int) -> Dict[str, Any]:
    result: Dict[str, Any] = {"path": str(path), "hits": 0, "snippets": []}
    text = read_text_bounded(path, max_file_bytes)
    if text is None:
        return result

    flags = re.MULTILINE
    if ignore_case:
        flags |= re.IGNORECASE

    it: Iterable[Tuple[int, str]]
    lines = text.splitlines()
    try:
        if regex:
            r = re.compile(pattern, flags)
            matches = [m for m in r.finditer(text)]
            # Map match spans back to line numbers (approx by scanning lines)
            # Faster: check each line
            for idx, line in enumerate(lines, start=1):
                if r.search(line):
                    start = max(1, idx - context)
                    end = min(len(lines), idx + context)
                    snippet_ctx = [{"line": i, "text": lines[i-1]} for i in range(start, end+1)]
                    result["snippets"].append({"line": idx, "start": start, "end": end, "context": snippet_ctx})
                    if len(result["snippets"]) >= per_file_limit:
                        break
        else:
            needle = pattern if not ignore_case else pattern.lower()
            for idx, line in enumerate(lines, start=1):
                hay = line if not ignore_case else line.lower()
                if needle in hay:
                    start = max(1, idx - context)
                    end = min(len(lines), idx + context)
                    snippet_ctx = [{"line": i, "text": lines[i-1]} for i in range(start, end+1)]
                    result["snippets"].append({"line": idx, "start": start, "end": end, "context": snippet_ctx})
                    if len(result["snippets"]) >= per_file_limit:
                        break
    except re.error:
        # invalid regex -> no hits
        return result

    result["hits"] = len(result["snippets"])
    return result

def dir_ascii_tree(root: Path, depth: int = 2, limit: int = 200,
                   excludes: Iterable[str] = DEFAULT_EXCLUDES_DIRS) -> str:
    excludes_norm = {fc.normalize(e) for e in excludes}
    lines: List[str] = [str(root.resolve())]

    def _ls(p: Path) -> List[Path]:
        try:
            xs = list(p.iterdir())
        except Exception:
            return []
        xs.sort(key=lambda x: (not x.is_dir(), x.name.lower()))
        return xs

    def _tree(p: Path, prefix: str, d: int, budget: List[int]):
        if d <= 0 or budget[0] <= 0:
            return
        items = [c for c in _ls(p) if fc.normalize(c.name) not in excludes_norm]
        shown = 0
        for i, child in enumerate(items):
            if budget[0] <= 0:
                break
            connector = "└── " if i == len(items) - 1 else "├── "
            lines.append(f"{prefix}{connector}{child.name}")
            budget[0] -= 1
            shown += 1
            if child.is_dir():
                ext = "    " if i == len(items) - 1 else "│   "
                _tree(child, prefix + ext, d - 1, budget)
        remaining = len(items) - shown
        if remaining > 0 and budget[0] <= 0:
            lines.append(f"{prefix}… (+{remaining} more)")

    _tree(root, "", depth, [limit])
    return "\n".join(lines)

# ---------------- Discovery (dirs) ----------------

def discover_dirs(keyword: str,
                  bases: List[Path],
                  aliases: Dict[str, List[str]],
                  must_parent_any: List[str],
                  must_parent_all: List[str],
                  not_parent: List[str],
                  name_exact: List[str],
                  name_regex: List[str]) -> List[Path]:
    alias_tokens = fc.expand_aliases(keyword, aliases)
    exact_norm = [fc.normalize(x) for x in name_exact]
    regex_objs = []
    for r in name_regex:
        try:
            regex_objs.append(re.compile(r, re.IGNORECASE))
        except re.error:
            pass

    matches: List[Path] = []
    for base in bases:
        base = base.expanduser().resolve()
        if not base.exists():
            continue
        for root, dirs, _files in os.walk(base):
            # prune obvious excludes
            dirs[:] = [d for d in dirs if fc.normalize(d) not in {fc.normalize(x) for x in DEFAULT_EXCLUDES_DIRS}]
            for d in dirs:
                dn = fc.normalize(d)
                # alias check (contains either way)
                ok_alias = any(a in dn or dn in a for a in alias_tokens)
                if not ok_alias:
                    continue
                # name exact / regex (if provided)
                if exact_norm and dn not in exact_norm:
                    continue
                if regex_objs and not any(r.search(d) for r in regex_objs):
                    continue

                candidate = Path(root) / d
                comps = [fc.normalize(p) for p in candidate.parts]
                # must any / all / none filters
                if must_parent_any:
                    if not any(any(n in c or c in n for n in [fc.normalize(x) for x in must_parent_any]) for c in comps):
                        continue
                if must_parent_all:
                    needed = [fc.normalize(x) for x in must_parent_all]
                    def present(n: str) -> bool:
                        return any(n in c or c in n for c in comps)
                    if not all(present(n) for n in needed):
                        continue
                if not_parent:
                    banned = [fc.normalize(x) for x in not_parent]
                    if any(n in c or c in n for c in comps for n in banned):
                        continue

                matches.append(candidate)

    # de-dup, stable-ish
    uniq = sorted(set([m.resolve() for m in matches]), key=lambda p: str(p).lower())
    return uniq

# ---------------- Grep stage (parallel) ----------------

def iter_files_under_dirs(dirs: List[Path],
                          include_globs: List[str],
                          exclude_globs: List[str],
                          not_parent: List[str] = None) -> List[Path]:
    files: List[Path] = []
    not_parent_norm = {fc.normalize(x) for x in (not_parent or [])}
    
    for d in dirs:
        if not d.exists():
            continue
        for root, subdirs, fs in os.walk(d):
            subdirs[:] = [x for x in subdirs if fc.normalize(x) not in {fc.normalize(y) for y in DEFAULT_EXCLUDES_DIRS}]
            
            # Apply not_parent filter to path components
            if not_parent_norm:
                root_path = Path(root)
                parts_norm = {fc.normalize(p) for p in root_path.parts}
                if parts_norm & not_parent_norm:  # Intersection = has excluded parent
                    continue
            
            for f in fs:
                p = Path(root) / f
                name = p.name
                if include_globs and not match_globs(name, include_globs):
                    continue
                if exclude_globs and match_globs(name, exclude_globs):
                    continue
                files.append(p)
    return files

def grep_files_parallel(files: List[Path],
                        pattern: str,
                        regex: bool,
                        ignore_case: bool,
                        per_file_limit: int,
                        context: int,
                        max_file_bytes: int,
                        workers: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not files:
        return results
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [
            ex.submit(grep_file, p, pattern, regex, ignore_case, per_file_limit, context, max_file_bytes)
            for p in files
        ]
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception:
                r = {"path": "", "hits": 0, "snippets": []}
            if r.get("hits", 0) > 0:
                results.append(r)
    return results

# ---------------- Scoring / Clustering ----------------

def _suffix_weight(path: Path, weights: Dict[str, float]) -> float:
    """Return the best weight for a path based on suffix keys.
    Supports multi-suffix keys like '.launch.py' by picking the longest
    matching key that the filename ends with. Falls back to last suffix.
    """
    name = path.name.lower()
    best_w = 1.0
    best_len = 0
    for k, v in weights.items():
        ks = str(k).lower().strip()
        if not ks:
            continue
        if name.endswith(ks) and len(ks) > best_len:
            best_len = len(ks)
            try:
                best_w = float(v)
            except Exception:
                best_w = 1.0
    if best_len > 0:
        return best_w
    # Fallback to simple last suffix
    return float(weights.get(path.suffix, 1.0))

def detect_definition_boost(file_path: Path, pattern: str, snippets: List[Dict[str, Any]]) -> float:
    """Boost score if file appears to DEFINE the keyword (not just mention it).
    
    Looks for:
    - Root README.md in project directory matching keyword (projects/amp/README.md)
    - H1 headers (any H1 in a root README is likely a definition)
    - "Keyword stands for" patterns
    - Definition lines ("Keyword: explanation" or "Keyword — explanation")
    
    Returns boost multiplier (1.0 = no boost, 5.0 = strong definition signal)
    """
    import re
    
    boost = 1.0
    
    # Extract keyword from pattern (remove regex chars if needed)
    # For simple cases, use the pattern as-is; for regex, extract first word group
    keyword = pattern.lower()
    if '|' in pattern or '(' in pattern or '[' in pattern:
        # Try to extract first meaningful word
        match = re.search(r'\w{3,}', pattern)
        if match:
            keyword = match.group(0).lower()
    
    # Build a sample of content from snippets
    content_sample = "\n".join([s.get("text", "") for s in snippets[:10]])
    
    # **STRONGEST SIGNAL**: README.md in a directory matching the keyword
    # e.g., projects/amp/README.md when searching for "amp"
    if file_path.name.lower() == "readme.md":
        parts = [p.lower() for p in file_path.parts]
        # Check if keyword appears in the path (projects/amp, robots/spot, etc.)
        if keyword in parts:
            # Find index of keyword and check if README is in that directory or one level down
            try:
                kw_idx = parts.index(keyword)
                # If README is at projects/amp/README.md (keyword at -2)
                if len(parts) >= 2 and parts[-2] == keyword:
                    boost = 8.0  # VERY strong signal - root project README
                # Or if it's one level deeper like projects/amp/docs/README.md
                elif kw_idx >= 0 and kw_idx < len(parts) - 1:
                    boost = 2.0  # Mild boost for sub-directories
            except ValueError:
                pass
    
    # Check for definition patterns in content
    # H1 header (any H1 is a definition candidate)
    if re.search(r"^#\s+\w+", content_sample, re.M):
        boost = max(boost, 2.5)  # Boost if we found an H1
    
    # "X stands for Y" pattern
    if re.search(rf"\b{re.escape(keyword)}\b\s+stands\s+for", content_sample, re.I):
        boost = max(boost, 3.5)
    
    # Definition line: "KEYWORD: " or "KEYWORD — "
    if re.search(rf"^{re.escape(keyword)}\s*[-:—]", content_sample, re.M | re.I):
        boost = max(boost, 3.0)
    
    return boost

def file_score(r: Dict[str, Any], weights: Dict[str, float], pattern: str = "") -> float:
    p = Path(r["path"])
    w = _suffix_weight(p, weights)
    base_score = r["hits"] * w + 0.1 * len(r.get("snippets", []))
    
    # Apply definition boost if pattern is provided
    if pattern:
        definition_boost = detect_definition_boost(p, pattern, r.get("snippets", []))
        base_score *= definition_boost
    # Authority directory hint boost / demotion for low-authority dirs
    parts = {s.lower() for s in p.parts}
    if parts & {"msg", "srv", "urdf", "description", "action"}:
        base_score *= 1.4
    if parts & {"legacy", "archived", "deprecated"}:
        base_score *= 0.85
    if parts & {"examples", "example", "test", "tests"}:
        base_score *= 0.9
    # Slight bonus for README.md (tends to be authoritative)
    if p.name.lower() == "readme.md":
        base_score *= 1.1
    if r.get("filename_hit"):
        base_score *= 2.0

    return base_score

def cluster_by_prefix(paths: List[str]) -> Dict[str, List[str]]:
    return fc.common_prefix_components([Path(p) for p in paths])

# ---------------- Probe orchestration ----------------

def main():
    ap = argparse.ArgumentParser(
        description="One-shot scout: discover → grep → rank → (peek/read) → JSON bundle for LLMs."
    )
    ap.add_argument("keyword", help="Directory keyword/alias (e.g., spot, ros, amp)")
    ap.add_argument("pattern", help="Grep pattern (literal or regex with --regex)")

    ap.add_argument("-b", "--base", action="append", required=True,
                    help="Base path(s) to search. Repeatable.")
    ap.add_argument("--include", default=None,
                    help="Comma-separated globs to include (default from config or sane defaults)")
    ap.add_argument("--exclude", default=None,
                    help="Comma-separated globs to exclude (default from config or sane defaults)")
    ap.add_argument("--exclude-dirs", action="append", default=[],
                    help="Additional directory names to skip (repeatable)")

    # Discovery filters
    ap.add_argument("--content-first", action="store_true",
                    help="Skip directory name matching; search entire base for pattern first, then cluster results. "
                         "More comprehensive but slower. Recommended for queries where keyword != directory name.")
    ap.add_argument("--must-parent", action="append", help="ANY of these parent path components")
    ap.add_argument("--must-parent-all", action="append", help="ALL of these parent path components")
    ap.add_argument("--not-parent", action="append", help="NONE of these parent path components")
    ap.add_argument("--name-exact", action="append", help="Only directory names exactly equal (CSV/repeat)")
    ap.add_argument("--name-regex", action="append", help="Only directory names matching regex (repeat)")

    # Grep flags
    ap.add_argument("--regex", action="store_true", help="Treat pattern as regex")
    ap.add_argument("-i", "--ignore-case", action="store_true", help="Case-insensitive")
    ap.add_argument("-C", "--context", type=int, default=DEFAULT_CONTEXT, help="Context lines (default: 2)")
    ap.add_argument("--per-file-limit", type=int, default=DEFAULT_PER_FILE_LIMIT, help="Snippets per file (default: 20)")
    ap.add_argument("--total-limit", type=int, default=DEFAULT_TOTAL_LIMIT, help="Global snippet cap (default: 500)")
    ap.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES, help="Max bytes read per file")
    ap.add_argument("--workers", type=int, default=4, help="Parallel grep workers (default: 4)")

    # Enrichment
    ap.add_argument("--top-files", type=int, default=DEFAULT_TOP_FILES, help="Ranked top-N files to return")
    ap.add_argument("--peek", action="store_true", help="Include head/tail previews for top files")
    ap.add_argument("--peek-head-lines", type=int, default=400, help="Head lines for peek (default 400)")
    ap.add_argument("--peek-tail-lines", type=int, default=80, help="Tail lines for peek (default 80)")
    ap.add_argument("--read-bytes", type=int, default=0, help="Include first N bytes of top files (0=off)")
    ap.add_argument("--ascii-tree", action="store_true", help="Include a bounded ASCII tree per matched dir")

    # Config / Profiles / Budget
    ap.add_argument("--config", action="append", help="Extra config path(s) to merge (.yaml)")
    ap.add_argument("--profile", help="Profile name from config to preload flags")
    ap.add_argument("--budget-tokens", type=int, default=0, help="Trim JSON bundle to fit approx token budget (0=off)")

    # Output & UX
    ap.add_argument("--json", action="store_true", help="Emit JSON (recommended)")
    ap.add_argument("--output", help="Write JSON to file")
    ap.add_argument("--debug", action="store_true", help="Verbose debug logging to stderr")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colors in human output")

    # Path prefixes (for RAG scoping)
    ap.add_argument("--emit-path-prefixes", action="store_true",
                    help="After JSON, also print unique directory prefixes (one per line) for top files.")
    ap.add_argument("--prefixes-only", action="store_true",
                    help="Print only unique directory prefixes (one per line) and exit (no JSON).")

    # Search breadth & filename channel
    ap.add_argument("--include-all", action="store_true", help="Do not limit by include globs (search all filetypes)")
    ap.add_argument("--file-name-regex", action="append", help="File name regex (repeat or CSV)")
    ap.add_argument("--file-name-globs", action="append", help="File name globs (repeat or CSV)")
    ap.add_argument("--filename-weight", type=float, default=2.0, help="Score multiplier for filename matches")

    args = ap.parse_args()

    # Load config (global + per-repo + extras)
    extra_cfg_paths: List[Path] = []
    if args.config:
        extra_cfg_paths.extend([Path(p).expanduser().resolve() for p in args.config])
    # also search for per-repo config
    per_repo_paths = []
    for b in args.base:
        pr = Path(b).expanduser().resolve() / ".focus_config.yaml"
        per_repo_paths.append(pr)
    cfg = fc.load_config(extra_paths=per_repo_paths + extra_cfg_paths)

    # Prepare merged kwargs from profile
    base_kwargs = {
        "include": args.include,
        "exclude": args.exclude,
        "must_parent": args.must_parent,
        "must_parent_all": args.must_parent_all,
        "not_parent": args.not_parent,
        "name_exact": args.name_exact,
        "name_regex": args.name_regex,
        "file_name_regex": args.file_name_regexp if hasattr(args, 'file_name_regexp') else args.file_name_regex,
        "file_name_globs": args.file_name_globs,
        "filename_weight": args.filename_weight,
        "top_files": args.top_files,
        "peek": args.peek,
        "peek_head_lines": args.peek_head_lines,
        "peek_tail_lines": args.peek_tail_lines,
        "read_bytes": args.read_bytes,
        "ascii_tree": args.ascii_tree,
        "regex": args.regex,
        "ignore_case": args.ignore_case,
        "context": args.context,
        "per_file_limit": args.per_file_limit,
        "total_limit": args.total_limit,
        "max_file_bytes": args.max_file_bytes,
        "workers": args.workers,
    }
    merged = fc.apply_profile(base_kwargs, cfg, args.profile)

    include_globs = fc.parse_csv_list(merged.get("include")) or cfg.defaults.get("include", DEFAULT_INCLUDE_GLOBS)
    exclude_globs = fc.parse_csv_list(merged.get("exclude")) or cfg.defaults.get("exclude", DEFAULT_EXCLUDE_GLOBS)
    must_parent_any = fc.parse_csv_list(merged.get("must_parent"))
    must_parent_all = fc.parse_csv_list(merged.get("must_parent_all"))
    not_parent = fc.parse_csv_list(merged.get("not_parent"))
    name_exact = fc.parse_csv_list(merged.get("name_exact"))
    name_regex = fc.parse_csv_list(merged.get("name_regex"))
    file_name_regex = fc.parse_csv_list(merged.get("file_name_regex"))
    file_name_globs = fc.parse_csv_list(merged.get("file_name_globs"))
    filename_weight = float(merged.get("filename_weight", args.filename_weight))

    # Debug log helper
    def log(msg: str):
        if args.debug:
            sys.stderr.write(f"[focus_probe] {msg}\n")

    bases = [Path(b).expanduser().resolve() for b in args.base]
    missing = [str(b) for b in bases if not b.exists()]
    if missing:
        sys.stderr.write("Warning: base path(s) not found:\n")
        for m in missing:
            sys.stderr.write(f"  - {m}\n")

    t0 = time.time()
    
    # Content-first mode: skip directory discovery, search entire base
    if args.content_first:
        log("content-first mode: searching entire base without directory name filtering")
        dirs = bases  # Use base directories directly
        log(f"using {len(dirs)} base dir(s) in {time.time() - t0:.3f}s")
        # In content-first mode, if user didn't explicitly provide include globs,
        # do not limit by default (let grep consider all file types, binary guard still applies)
        if (not args.include and not merged.get("include")) or args.include_all:
            include_globs = []
    else:
        # Normal mode: discover directories by keyword first
        dirs = discover_dirs(
            keyword=args.keyword,
            bases=bases,
            aliases=cfg.aliases,
            must_parent_any=must_parent_any,
            must_parent_all=must_parent_all,
            not_parent=not_parent,
            name_exact=name_exact,
            name_regex=name_regex,
        )
        log(f"discovered {len(dirs)} dirs in {time.time() - t0:.3f}s")
        if args.include_all:
            include_globs = []

    # If only prefixes requested and no candidate dirs, exit 1 (no prefixes)
    if args.prefixes_only and not dirs:
        return 1

    files = iter_files_under_dirs(dirs, include_globs, exclude_globs, not_parent=not_parent)
    log(f"candidate files: {len(files)}")

    t1 = time.time()
    grep_results = grep_files_parallel(
        files=files,
        pattern=args.pattern,
        regex=merged.get("regex", False),
        ignore_case=merged.get("ignore_case", False),
        per_file_limit=int(merged.get("per_file_limit", DEFAULT_PER_FILE_LIMIT)),
        context=int(merged.get("context", DEFAULT_CONTEXT)),
        max_file_bytes=int(merged.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)),
        workers=int(merged.get("workers", 4)),
    )
    log(f"grep hits in {time.time() - t1:.3f}s")

    # Filename channel: promote files whose names match provided patterns
    name_rx = []
    for r in (file_name_regex or []):
        try:
            name_rx.append(re.compile(r, re.IGNORECASE))
        except re.error:
            pass
    name_globs = file_name_globs or []
    by_path: Dict[str, Dict[str, Any]] = {r.get("path"): r for r in grep_results if r.get("path")}
    for p in files:
        nm = p.name
        matched = False
        if name_rx and any(rx.search(nm) for rx in name_rx):
            matched = True
        if not matched and name_globs and any(fnmatch.fnmatch(nm, g) for g in name_globs):
            matched = True
        if matched:
            key = str(p)
            if key in by_path:
                by_path[key]["filename_hit"] = True
            else:
                by_path[key] = {"path": key, "hits": 0, "snippets": [], "filename_hit": True}
    grep_results = list(by_path.values())

    # Flatten & cap to total snippets limit
    total_limit = int(merged.get("total_limit", DEFAULT_TOTAL_LIMIT))
    if total_limit > 0:
        # clamp per file during scoring by truncating snippet lists
        for r in grep_results:
            if len(r.get("snippets", [])) > total_limit:
                r["snippets"] = r["snippets"][:total_limit]

    # Weighted scoring
    weights = {str(k): float(v) for k, v in cfg.weights.items()}
    for k, v in {
        ".msg": 2.0, ".idl": 1.8, ".srv": 1.6, ".urdf": 2.0, ".xacro": 2.0,
        ".toml": 1.5, ".xml": 1.2
    }.items():
        weights.setdefault(k, v)
    scored = []
    for r in grep_results:
        if r.get("hits", 0) <= 0 and not r.get("filename_hit"):
            continue
        s = file_score(r, weights, pattern=args.pattern)
        scored.append((s, r))
    scored.sort(key=lambda x: x[0], reverse=True)

    top_n = int(merged.get("top_files", DEFAULT_TOP_FILES))
    top = [r for _s, r in scored[:top_n]]

    # Compute unique path prefixes from top files
    def _path_prefixes(entries: List[Dict[str, Any]]) -> List[str]:
        uniq = sorted({str(Path(e.get("path", "")).expanduser().resolve().parent)
                       for e in entries if e.get("path")}, key=str.lower)
        return uniq
    prefixes = _path_prefixes(top)

    # prefixes-only mode: print one-per-line and exit (0 if any, else 1)
    if args.prefixes_only:
        for p in prefixes:
            print(p)
        return 0 if prefixes else 1

    # Enrichment: peek & bounded read
    if merged.get("peek"):
        head_lines = int(merged.get("peek_head_lines", 80))
        tail_lines = int(merged.get("peek_tail_lines", 40))
        max_bytes = int(merged.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES))
        any_symbol_found = False
        inferred_symbol: Optional[str] = None
        for r in top:
            p = Path(r["path"])
            # Prefer focus_read for bounded, binary-safe peeks when available
            if _HAVE_FOCUS_READ:
                try:
                    head_res = _focus_read.read_one_file(
                        p,
                        head=head_lines,
                        tail=None,
                        lines=None,
                        max_bytes=max_bytes,
                        skip_binary=True,
                    )
                    tail_res = _focus_read.read_one_file(
                        p,
                        head=None,
                        tail=tail_lines,
                        lines=None,
                        max_bytes=max_bytes,
                        skip_binary=True,
                    )
                    r["peek_head"] = [{"line": ln["line"], "text": ln["text"]} for ln in head_res.get("content", [])]
                    r["peek_tail"] = [{"line": ln["line"], "text": ln["text"]} for ln in tail_res.get("content", [])]
                except Exception:
                    text = read_text_bounded(p, max_bytes)
                    if text:
                        lines = text.splitlines()
                        r["peek_head"] = [{"line": i+1, "text": lines[i]} for i in range(min(head_lines, len(lines)))]
                        tail = max(0, len(lines) - tail_lines)
                        r["peek_tail"] = [{"line": i+1, "text": lines[i]} for i in range(tail, len(lines))]
                else:
                    r["peek_head"] = []
                    r["peek_tail"] = []
            else:
                text = read_text_bounded(p, max_bytes)
                if text:
                    lines = text.splitlines()
                    r["peek_head"] = [{"line": i+1, "text": lines[i]} for i in range(min(head_lines, len(lines)))]
                    tail = max(0, len(lines) - tail_lines)
                    r["peek_tail"] = [{"line": i+1, "text": lines[i]} for i in range(tail, len(lines))]
                else:
                    r["peek_head"] = []
                    r["peek_tail"] = []

            # Lightweight extraction for authority types
            try:
                if p.suffix.lower() == ".msg":
                    full = read_text_bounded(p, max_bytes) or ""
                    fields = _extract_msg_fields(full)
                    if fields:
                        r["extracted_msg_fields"] = fields[:50]
                        # Attempt nested message extraction (bounded)
                        types = _parse_msg_types(full)[:8]
                        if types:
                            search_roots = list(bases)
                            search_roots.append(p.parent)
                            nested = _extract_msg_nested(types, search_roots, max_depth=2, max_types=20)
                            if nested:
                                r["extracted_msg_nested"] = nested
                if p.suffix.lower() in {".urdf", ".xacro"}:
                    full = read_text_bounded(p, max_bytes) or ""
                    joints = _extract_urdf_joints(full)
                    if joints:
                        r["extracted_urdf_joints"] = sorted(set(joints))[:200]
                # Basic Python symbol block extraction when pattern looks like a name
                sym = None
                try:
                    # derive symbol hint from args.pattern
                    if args.pattern and isinstance(args.pattern, str):
                        m = re.search(r"\b([A-Za-z_]\w{2,})\b", args.pattern)
                        if m:
                            sym = m.group(1)
                except Exception:
                    sym = None
                if sym and p.suffix.lower() == ".py":
                    full = read_text_bounded(p, max_bytes) or ""
                    block = _extract_python_symbol_block(full, sym, max_lines=80)
                    if block:
                        r["extracted_symbol"] = {"name": sym, "block": block}
                        any_symbol_found = True
                        inferred_symbol = sym
            except Exception:
                pass

        # Cross-file symbol search if not found in top files
        if not any_symbol_found and inferred_symbol:
            symbols_list = []
            count = 0
            for fp in files:
                if count >= 1:
                    break
                if fp.suffix.lower() != ".py":
                    continue
                try:
                    full = read_text_bounded(fp, max_bytes) or ""
                    blk = _extract_python_symbol_block(full, inferred_symbol, max_lines=80)
                    if blk:
                        symbols_list.append({"name": inferred_symbol, "path": str(fp), "block": blk})
                        count += 1
                except Exception:
                    continue
            if symbols_list:
                bundle_symbols = bundle.get("symbols") or []
                bundle_symbols.extend(symbols_list)
                bundle["symbols"] = bundle_symbols

    if int(merged.get("read_bytes", 0)) > 0:
        rb = int(merged.get("read_bytes", 0))
        for r in top:
            p = Path(r["path"])
            content = read_text_bounded(p, rb)
            r["content_head"] = content if content is not None else ""

    # Directory trees (optional)
    trees: Dict[str, str] = {}
    if merged.get("ascii_tree"):
        for d in dirs:
            trees[str(d)] = dir_ascii_tree(d, depth=2, limit=200, excludes=DEFAULT_EXCLUDES_DIRS)

    # Clusters (by directory)
    clusters = cluster_by_prefix([t["path"] for t in top])

    bundle: Dict[str, Any] = {
        "keyword": args.keyword,
        "pattern": args.pattern,
        "regex": bool(merged.get("regex", False)),
        "case_insensitive": bool(merged.get("ignore_case", False)),
        "bases": [str(b) for b in bases],
        "filters": {
            "must_parent_any": must_parent_any,
            "must_parent_all": must_parent_all,
            "not_parent": not_parent,
            "name_exact": name_exact,
            "name_regex": name_regex,
            "include_globs": include_globs,
            "exclude_globs": exclude_globs,
            # Effective directory excludes: built-ins plus any user-provided extras
            "exclude_dirs": sorted({*{str(x) for x in DEFAULT_EXCLUDES_DIRS}, *{
                y.strip() for chunk in (args.exclude_dirs or []) for y in str(chunk).split(',') if y.strip()
            }}, key=str.lower),
        },
        "dirs_found": len(dirs),
        "files_scanned": len(files),
        "files_with_hits": len(grep_results),
        "top_count": len(top),
        "top_files": top,
        "clusters": clusters,
        "trees": trees,
        "weights": weights,
        "profile": args.profile or "",
        "path_prefixes": prefixes,
    }

    # Token budget guard (approx)
    if int(args.budget_tokens or 0) > 0:
        bundle = fc.trim_bundle_to_token_budget(bundle, int(args.budget_tokens))

    # Attach a rough token estimate for downstream consumers
    try:
        bundle["token_estimate"] = fc.estimate_tokens_from_json(bundle)
    except Exception:
        # Best-effort only; omit on failure
        pass

    # Output
    if args.json or args.output:
        data = json.dumps(bundle, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(data, encoding="utf-8")
        if args.json:
            print(data)
        # Optionally emit plain prefixes after JSON
        if args.emit_path_prefixes and prefixes:
            for p in prefixes:
                print(p)
    else:
        # Human summary
        use_color = fc.is_tty() and not args.no_color
        print(fc.colorize(f"Dirs: {len(dirs)}   Files scanned: {len(files)}   Files with hits: {len(grep_results)}",
                          fc.Ansi.BOLD, enable=use_color))
        for i, r in enumerate(top, 1):
            p = r["path"]
            hits = r.get("hits", 0)
            print(fc.colorize(f"[{i}] {p}  (hits={hits})", fc.Ansi.GREEN if hits else fc.Ansi.DIM, enable=use_color))
        if merged.get("ascii_tree") and trees:
            print(fc.colorize("\n--- Matched Directory Trees ---", fc.Ansi.BOLD, enable=use_color))
            for k, v in trees.items():
                print(fc.colorize(f"\n{k}", fc.Ansi.YELLOW, enable=use_color))
                print(v)
        # Optionally emit plain prefixes after summary
        if args.emit_path_prefixes and prefixes:
            for p in prefixes:
                print(p)

    # Exit code: success even if zero hits (valid run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
