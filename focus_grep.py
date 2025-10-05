#!/usr/bin/env python3
# file: focus_grep.py
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Iterable, Iterator, Tuple
import os, sys, re, argparse, json, fnmatch

DEFAULT_EXCLUDES_DIR = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "node_modules", "__pycache__",
    "build", "dist", ".venv", "venv", ".mypy_cache", ".pytest_cache"
}
# Broaden defaults to include common ROS/robot and config/doc types
DEFAULT_INCLUDE_GLOBS = [
    "*.py", "*.pyw", "*.md", "*.rst", "*.yaml", "*.yml", "*.toml", "*.json",
    "*.launch.py", "*.xml", "*.msg", "*.idl", "*.srv", "*.action", "*.urdf", "*.xacro",
    "CMakeLists.txt", "Dockerfile*", "*.txt"
]
DEFAULT_EXCLUDE_GLOBS = ["*.min.js", "*.lock", "*.bin", "*.exe", "*.dll", "*.so", "*.dylib"]
DEFAULT_MAX_FILE_BYTES = 2_500_000  # ~2.5MB cap per file
DEFAULT_MAX_HITS_PER_FILE = 20
DEFAULT_MAX_TOTAL_HITS = 500
DEFAULT_CONTEXT = 2

# Extensions that should always be treated as text (bypass binary heuristics)
TEXT_EXTENSIONS = {
    ".py", ".pyw", ".md", ".rst", ".yaml", ".yml", ".toml", ".json", ".txt",
    ".msg", ".idl", ".srv", ".action", ".urdf", ".xacro", ".launch", ".xml",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".cmake"
}

def is_probably_binary(data: bytes) -> bool:
    # quick heuristic
    if b"\x00" in data:
        return True
    textish = sum(32 <= b <= 126 or b in (9,10,13) for b in data[:1024])
    return textish < 0.85 * min(1024, len(data))

def should_consider_file(path: Path, include_globs: List[str], exclude_globs: List[str]) -> bool:
    name = path.name
    # include if matches any include_glob; if include_globs empty, include all
    if include_globs:
        if not any(fnmatch.fnmatch(name, g) for g in include_globs):
            return False
    # exclude if matches any exclude_glob
    if any(fnmatch.fnmatch(name, g) for g in exclude_globs):
        return False
    return True

def iter_files(root: Path,
               include_globs: List[str],
               exclude_globs: List[str],
               exclude_dirs: List[str]) -> Iterator[Path]:
    ex_dirs_norm = {d.lower() for d in exclude_dirs}
    for r, dirs, files in os.walk(root):
        # prune directories
        dirs[:] = [d for d in dirs if d.lower() not in ex_dirs_norm]
        for f in files:
            p = Path(r) / f
            if should_consider_file(p, include_globs, exclude_globs):
                yield p

def read_text_safely(p: Path, max_bytes: int) -> str | None:
    try:
        with open(p, "rb") as fh:
            buf = fh.read(max_bytes + 1)
        # Treat known texty files as text regardless of heuristic
        name = p.name
        suffix = p.suffix.lower()
        force_text = (
            suffix in TEXT_EXTENSIONS
            or name == "CMakeLists.txt"
            or name.startswith("Dockerfile")
        )
        if not force_text and is_probably_binary(buf):
            return None
        return buf[:max_bytes].decode("utf-8", errors="ignore")
    except Exception:
        return None

def grep_text(lines: List[str],
              pattern: str,
              regex: bool,
              case_insensitive: bool) -> List[Tuple[int, str]]:
    hits = []
    flags = re.IGNORECASE if case_insensitive else 0
    if regex:
        try:
            rx = re.compile(pattern, flags)
        except re.error as e:
            raise ValueError(f"Invalid regex: {e}")
        for i, line in enumerate(lines, 1):
            if rx.search(line):
                hits.append((i, line.rstrip("\n")))
    else:
        needle = pattern.lower() if case_insensitive else pattern
        for i, line in enumerate(lines, 1):
            hay = line.lower() if case_insensitive else line
            if needle in hay:
                hits.append((i, line.rstrip("\n")))
    return hits

def make_snippets(lines: List[str],
                  hit_lines: List[Tuple[int,str]],
                  context: int,
                  per_file_limit: int) -> List[Dict]:
    snippets = []
    used = 0
    n = len(lines)
    for ln, _ in hit_lines:
        if used >= per_file_limit:
            break
        start = max(1, ln - context)
        end   = min(n, ln + context)
        block = []
        for i in range(start, end + 1):
            block.append({"line": i, "text": lines[i-1].rstrip("\n")})
        snippets.append({
            "line": ln,
            "start": start,
            "end": end,
            "context": block
        })
        used += 1
    return snippets

def load_input_paths(paths: List[str], stdin_paths: bool) -> List[Path]:
    acc: List[Path] = []
    if stdin_paths:
        for raw in sys.stdin.read().splitlines():
            raw = raw.strip()
            if raw:
                acc.append(Path(raw))
    for p in paths:
        acc.append(Path(p))
    # normalize to existing dirs/files
    norm: List[Path] = []
    for p in acc:
        rp = p.expanduser().resolve()
        if rp.exists():
            norm.append(rp)
    return norm

def search(paths: List[Path],
           pattern: str,
           regex: bool,
           case_insensitive: bool,
           include_globs: List[str],
           exclude_globs: List[str],
           exclude_dirs: List[str],
           max_file_bytes: int,
           context: int,
           per_file_limit: int,
           total_limit: int) -> Dict:
    results = []
    total_hits = 0
    for p in paths:
        if p.is_file():
            candidates = [p]
        else:
            candidates = list(iter_files(p, include_globs, exclude_globs, exclude_dirs))
        for f in candidates:
            if total_hits >= total_limit:
                break
            text = read_text_safely(f, max_file_bytes)
            if text is None:
                continue
            lines = text.splitlines(True)
            hit_lines = grep_text(lines, pattern, regex, case_insensitive)
            if not hit_lines:
                continue
            snippets = make_snippets(lines, hit_lines, context=context, per_file_limit=per_file_limit)
            total_hits += len(snippets)
            results.append({
                "path": str(f),
                "hits": len(hit_lines),
                "snippets": snippets
            })
            if total_hits >= total_limit:
                break
    return {"pattern": pattern, "regex": regex, "case_insensitive": case_insensitive,
            "results": results, "total_snippets": total_hits}

def main():
    ap = argparse.ArgumentParser(description="Recursive focused grep with context and file filters.")
    ap.add_argument("pattern", help="Search pattern (regex if --regex, else literal substring).")
    ap.add_argument("paths", nargs="*", help="Directories or files to search (optional with --stdin-paths).")
    ap.add_argument("--regex", action="store_true",
                    help="#example: --regex 'teleop|wasd|rviz'")
    ap.add_argument("-i", "--ignore-case", action="store_true",
                    help="#example: -i to make search case-insensitive")
    ap.add_argument("--stdin-paths", action="store_true",
                    help="Read newline-separated paths from stdin (e.g., piped from focus_tree.py --paths-only). "
                         "#example: focus_tree.py spot -b ./bdai-main --paths-only | focus_grep.py teleop --stdin-paths")
    ap.add_argument("--include", action="append",
                    help="Comma-separated file globs to include. Default: common code/docs. "
                         "#example: --include '*.py,*.md,*.launch.py'")
    ap.add_argument("--exclude", action="append",
                    help="Comma-separated file globs to exclude. "
                         "#example: --exclude '*.min.js,*.lock'")
    ap.add_argument("--exclude-dirs", action="append", default=list(DEFAULT_EXCLUDES_DIR),
                    help="Directory names to exclude recursively. "
                         "#example: --exclude-dirs .git,__pycache__")
    ap.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES,
                    help=f"Max bytes to read per file (default {DEFAULT_MAX_FILE_BYTES}).")
    ap.add_argument("-C", "--context", type=int, default=DEFAULT_CONTEXT,
                    help=f"Context lines around each hit (default {DEFAULT_CONTEXT}). "
                         "#example: -C 3")
    ap.add_argument("--per-file-limit", type=int, default=DEFAULT_MAX_HITS_PER_FILE,
                    help=f"Max snippets per file (default {DEFAULT_MAX_HITS_PER_FILE}).")
    ap.add_argument("--total-limit", type=int, default=DEFAULT_MAX_TOTAL_HITS,
                    help=f"Max snippets total across all files (default {DEFAULT_MAX_TOTAL_HITS}).")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON for tool consumption instead of human-readable.")
    args = ap.parse_args()

    include_globs = []
    if args.include:
        for chunk in args.include:
            include_globs.extend([g.strip() for g in chunk.split(",") if g.strip()])
    else:
        include_globs = list(DEFAULT_INCLUDE_GLOBS)

    exclude_globs = []
    if args.exclude:
        for chunk in args.exclude:
            exclude_globs.extend([g.strip() for g in chunk.split(",") if g.strip()])
    else:
        exclude_globs = list(DEFAULT_EXCLUDE_GLOBS)

    paths = load_input_paths(args.paths, args.stdin_paths)
    if not paths:
        print("No valid input paths. Provide paths or use --stdin-paths.", file=sys.stderr)
        sys.exit(2)

    data = search(
        paths=paths,
        pattern=args.pattern,
        regex=args.regex,
        case_insensitive=args.ignore_case,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        exclude_dirs=args.exclude_dirs,
        max_file_bytes=args.max_file_bytes,
        context=args.context,
        per_file_limit=args.per_file_limit,
        total_limit=args.total_limit,
    )

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # human-readable
    print(f"Pattern: {data['pattern']}  (regex={data['regex']}  ignore_case={data['case_insensitive']})")
    print(f"Total snippets: {data['total_snippets']}\n")
    sep = "\n" + "="*80 + "\n"
    first = True
    for entry in data["results"]:
        if not first:
            print(sep)
        first = False
        print(entry["path"])
        for sn in entry["snippets"]:
            print(f"  [L{sn['line']}]")
            for ln in sn["context"]:
                mark = ">" if ln["line"] == sn["line"] else " "
                print(f"   {mark} {ln['line']:>5}: {ln['text']}")
    # end

if __name__ == "__main__":
    main()
