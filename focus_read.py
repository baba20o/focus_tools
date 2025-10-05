#!/usr/bin/env python3
"""
focus_read.py - Bounded file reader for agentic workflows.

Safely reads files with hard limits:
- head/tail/line-range support
- max-bytes cap
- binary file detection
- JSON output
- Normalizes paths

Usage:
    python focus_read.py file.txt --head 50
    python focus_read.py file.py --lines 100:200 --json
    echo "path1\npath2" | python focus_read.py --stdin-paths --head 120 --json
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import argparse
import sys
import json


# -------- Utils -------- #

def is_probably_binary(p: Path, probe_bytes: int = 2048) -> bool:
    """Heuristic binary file detection."""
    try:
        with p.open("rb") as f:
            chunk = f.read(probe_bytes)
        if b"\x00" in chunk:
            return True
        # High fraction of non-printable bytes
        textish = bytes(range(32, 127)) + b"\n\r\t\b\f"
        weird = sum(b not in textish for b in chunk)
        return (len(chunk) > 0) and (weird / len(chunk) > 0.30)
    except Exception:
        return False


def normalize_path(p: Path) -> str:
    """Resolve to absolute path, fall back to string if resolution fails."""
    try:
        return str(p.resolve())
    except Exception:
        return str(p)


def read_text_safely(p: Path, max_bytes: int) -> Tuple[str, bool]:
    """
    Returns (text, truncated).
    Decodes as UTF-8 with replacement.
    Respects max_bytes cap.
    """
    read_bytes = 0
    chunks: List[bytes] = []
    try:
        with p.open("rb") as f:
            while True:
                need = min(65536, max_bytes - read_bytes)
                if need <= 0:
                    break
                buf = f.read(need)
                if not buf:
                    break
                chunks.append(buf)
                read_bytes += len(buf)
        data = b"".join(chunks)
        text = data.decode("utf-8", errors="replace")
        truncated = (p.stat().st_size > len(data))
        return text, truncated
    except Exception as e:
        return f"<<ERROR reading file: {e}>>", False


def select_lines(
    text: str,
    head: Optional[int],
    tail: Optional[int],
    lines: Optional[Tuple[int, Optional[int]]]
) -> Tuple[List[Tuple[int, str]], bool]:
    """
    Returns list of (line_num, line_text) and 'sliced' flag.
    Line numbers are 1-based.
    """
    all_lines = text.splitlines()
    n = len(all_lines)
    sliced = False

    if lines is not None:
        start, end = lines
        start = max(1, start)
        end = n if end is None else max(start, min(end, n))
        sel = list(enumerate(all_lines[start - 1:end], start))
        return sel, True

    if head is not None and tail is not None:
        # Head X + Tail Y
        top_n = max(0, min(head, n))
        bot_n = max(0, min(tail, n - top_n))
        head_part = list(enumerate(all_lines[:top_n], 1))
        tail_part = list(enumerate(all_lines[n - bot_n:], n - bot_n + 1))
        # Avoid overlap
        if head_part and tail_part and head_part[-1][0] >= tail_part[0][0]:
            tail_part = []
        return head_part + tail_part, True

    if head is not None:
        k = max(0, min(head, n))
        return list(enumerate(all_lines[:k], 1)), True

    if tail is not None:
        k = max(0, min(tail, n))
        return list(enumerate(all_lines[n - k:], n - k + 1)), True

    # No slicing: full file
    return list(enumerate(all_lines, 1)), False


# -------- Core -------- #

def read_one_file(
    path: Path,
    *,
    head: Optional[int],
    tail: Optional[int],
    lines: Optional[Tuple[int, Optional[int]]],
    max_bytes: int,
    skip_binary: bool
) -> Dict[str, Any]:
    """Read a single file with bounds and return structured result."""
    entry: Dict[str, Any] = {
        "path": normalize_path(path),
        "exists": path.exists(),
        "is_file": path.is_file(),
        "size_bytes": None,
        "binary": None,
        "error": None,
        "mode": None,  # "head" | "tail" | "lines" | "head+tail" | "full"
        "truncated_bytes": False,
        "sliced": False,
        "content": [],  # list of {"line": int, "text": str}
    }

    if not path.exists():
        entry["error"] = "not_found"
        return entry
    if not path.is_file():
        entry["error"] = "not_a_file"
        return entry

    try:
        st = path.stat()
        entry["size_bytes"] = st.st_size
    except Exception:
        pass

    is_bin = is_probably_binary(path)
    entry["binary"] = is_bin
    if is_bin and skip_binary:
        entry["error"] = "binary_skipped"
        return entry

    text, truncated = read_text_safely(path, max_bytes=max_bytes)
    entry["truncated_bytes"] = truncated

    # Determine mode
    if lines is not None:
        entry["mode"] = "lines"
    elif head is not None and tail is not None:
        entry["mode"] = "head+tail"
    elif head is not None:
        entry["mode"] = "head"
    elif tail is not None:
        entry["mode"] = "tail"
    else:
        entry["mode"] = "full"

    selected, sliced = select_lines(text, head, tail, lines)
    entry["sliced"] = sliced
    entry["content"] = [{"line": ln, "text": s} for (ln, s) in selected]
    return entry


def parse_lines_arg(spec: Optional[str]) -> Optional[Tuple[int, Optional[int]]]:
    """Parse --lines argument. Forms: '10', '10:20', ':50'"""
    if not spec:
        return None
    if ":" in spec:
        a, b = spec.split(":", 1)
        a = a.strip()
        b = b.strip()
        start = int(a) if a else 1
        end = int(b) if b else None
        return (start, end)
    else:
        start = int(spec)
        return (start, None)


def read_paths_from_stdin() -> List[Path]:
    """Read newline-separated paths from stdin."""
    paths: List[Path] = []
    for line in sys.stdin:
        s = line.strip()
        if not s:
            continue
        paths.append(Path(s))
    return paths


# -------- CLI -------- #

def main():
    ap = argparse.ArgumentParser(
        description="Bounded file reader for agentic workflows (head/tail/lines/max-bytes, skip-binary, JSON)."
    )
    ap.add_argument("paths", nargs="*", help="Files to read. Omit when using --stdin-paths.")
    ap.add_argument("--stdin-paths", action="store_true",
                    help="Read newline-separated file paths from STDIN.")
    ap.add_argument("--head", type=int, default=None,
                    help="Read first N lines.")
    ap.add_argument("--tail", type=int, default=None,
                    help="Read last N lines.")
    ap.add_argument("--lines", type=str, default=None,
                    help="Read specific line range. Forms: '10', '10:20', ':50'.")
    ap.add_argument("--bytes", dest="max_bytes", type=int, default=256 * 1024,
                    help="Max bytes to read per file (default: 262144).")
    ap.add_argument("--no-skip-binary", action="store_true",
                    help="Do not skip binary files (by default they are skipped).")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON object instead of pretty text.")
    ap.add_argument("--quiet-missing", action="store_true",
                    help="Suppress stderr warnings for missing/not-a-file.")
    args = ap.parse_args()

    # Input paths
    paths: List[Path] = []
    if args.stdin_paths:
        paths += read_paths_from_stdin()
    paths += [Path(p) for p in args.paths]
    if not paths:
        print("No input paths. Provide files or use --stdin-paths.", file=sys.stderr)
        sys.exit(2)

    # Mode validation
    lines_tuple = parse_lines_arg(args.lines)
    if (args.head is not None or args.tail is not None) and lines_tuple is not None:
        print("Choose either --head/--tail OR --lines, not both.", file=sys.stderr)
        sys.exit(2)

    results: List[Dict[str, Any]] = []
    for p in paths:
        entry = read_one_file(
            p,
            head=args.head,
            tail=args.tail,
            lines=lines_tuple,
            max_bytes=args.max_bytes,
            skip_binary=(not args.no_skip_binary),
        )
        if entry.get("error") in {"not_found", "not_a_file"} and not args.quiet_missing and not args.json:
            print(f"Warning: {entry['path']}: {entry['error']}", file=sys.stderr)
        results.append(entry)

    if args.json:
        bundle = {
            "count": len(results),
            "results": results
        }
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
        return

    # Pretty text output
    first = True
    for r in results:
        if not first:
            print("\n" + "-" * 80 + "\n")
        first = False
        hdr = f"{r['path']}"
        meta = []
        if r["size_bytes"] is not None:
            meta.append(f"{r['size_bytes']}B")
        if r["binary"] is True:
            meta.append("binary")
        if r["mode"]:
            meta.append(r["mode"])
        if r["truncated_bytes"]:
            meta.append("bytes_truncated")
        if r["sliced"]:
            meta.append("sliced")
        if r["error"]:
            meta.append(f"ERROR={r['error']}")
        if meta:
            hdr += "  [" + ", ".join(meta) + "]"
        print(hdr)
        for line in r["content"]:
            print(f"{line['line']:>6}: {line['text']}")


if __name__ == "__main__":
    main()
