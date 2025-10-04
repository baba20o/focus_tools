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

import focus_common as fc

# ---------------- Defaults / Guards ----------------

DEFAULT_EXCLUDES_DIRS = {".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__"}
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
                          exclude_globs: List[str]) -> List[Path]:
    files: List[Path] = []
    for d in dirs:
        if not d.exists():
            continue
        for root, subdirs, fs in os.walk(d):
            subdirs[:] = [x for x in subdirs if fc.normalize(x) not in {fc.normalize(y) for y in DEFAULT_EXCLUDES_DIRS}]
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

def file_score(r: Dict[str, Any], weights: Dict[str, float]) -> float:
    p = Path(r["path"])
    w = weights.get(p.suffix, 1.0)
    return r["hits"] * w + 0.1 * len(r.get("snippets", []))

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
    ap.add_argument("--peek-head-lines", type=int, default=80, help="Head lines for peek (default 80)")
    ap.add_argument("--peek-tail-lines", type=int, default=40, help="Tail lines for peek (default 40)")
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

    files = iter_files_under_dirs(dirs, include_globs, exclude_globs)
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

    # Flatten & cap to total snippets limit
    total_limit = int(merged.get("total_limit", DEFAULT_TOTAL_LIMIT))
    if total_limit > 0:
        # clamp per file during scoring by truncating snippet lists
        for r in grep_results:
            if len(r.get("snippets", [])) > total_limit:
                r["snippets"] = r["snippets"][:total_limit]

    # Weighted scoring
    weights = {str(k): float(v) for k, v in cfg.weights.items()}
    scored = []
    for r in grep_results:
        if r.get("hits", 0) <= 0:
            continue
        s = file_score(r, weights)
        scored.append((s, r))
    scored.sort(key=lambda x: x[0], reverse=True)

    top_n = int(merged.get("top_files", DEFAULT_TOP_FILES))
    top = [r for _s, r in scored[:top_n]]

    # Enrichment: peek & bounded read
    if merged.get("peek"):
        head_lines = int(merged.get("peek_head_lines", 80))
        tail_lines = int(merged.get("peek_tail_lines", 40))
        for r in top:
            p = Path(r["path"])
            text = read_text_bounded(p, int(merged.get("max_file_bytes", DEFAULT_MAX_FILE_BYTES)))
            if text:
                lines = text.splitlines()
                r["peek_head"] = [{"line": i+1, "text": lines[i]} for i in range(min(head_lines, len(lines)))]
                tail = max(0, len(lines) - tail_lines)
                r["peek_tail"] = [{"line": i+1, "text": lines[i]} for i in range(tail, len(lines))]
            else:
                r["peek_head"] = []
                r["peek_tail"] = []

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
        "dirs_found": len(dirs),
        "files_scanned": len(files),
        "files_with_hits": len(grep_results),
        "top_count": len(top),
        "top_files": top,
        "clusters": clusters,
        "trees": trees,
        "weights": weights,
        "profile": args.profile or "",
    }

    # Token budget guard (approx)
    if int(args.budget_tokens or 0) > 0:
        bundle = fc.trim_bundle_to_token_budget(bundle, int(args.budget_tokens))

    # Output
    if args.json or args.output:
        data = json.dumps(bundle, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(data, encoding="utf-8")
        if args.json:
            print(data)
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

    # Exit code: success even if zero hits (valid run)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
