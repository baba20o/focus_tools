#!/usr/bin/env python3
"""
focus_llm.py — Minimal LLM-orchestrated wrapper around focus_probe.

Flow (bounded agent, no RAG):
1) Classify: ask LLM to propose focus_probe params (profile/keyword/pattern/etc.)
2) Probe: run focus_probe with budget + params
3) Judge: ask LLM if evidence is sufficient; may propose a bounded follow-up
4) (Optional) Re-probe once with adjusted params
5) Answer: ask LLM to synthesize an answer using only the evidence

Env:
  OPENAI_API_KEY   (provided by user)
  OPENAI_MODEL     (e.g., gpt-4o-mini, gpt-4-turbo)

CLI:
  python focus_llm.py "How do I teleop Spot in RViz?" -b ./bdai-main
"""
from __future__ import annotations
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env variables must be set manually


PROMPTS_DIR = Path(__file__).parent / "prompts"


def _read_prompt(name: str) -> str:
    p = PROMPTS_DIR / name
    return p.read_text(encoding="utf-8")


def _require_env() -> Dict[str, str]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model = os.getenv("OPENAI_MODEL", "").strip()
    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY (set in environment or .env)")
    if not model:
        raise SystemExit("Missing OPENAI_MODEL (set in environment or .env)")
    return {"api_key": api_key, "model": model}


def call_openai(messages: List[Dict[str, str]], *, temperature: Optional[float] = None) -> str:
    """Minimal OpenAI Chat Completions call. Requires OPENAI_API_KEY/MODEL.
    Returns the assistant content as string.
    """
    creds = _require_env()
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        raise SystemExit("Install openai>=1.0: pip install openai")

    client = OpenAI(api_key=creds["api_key"])  # type: ignore
    kwargs: Dict[str, Any] = {"model": creds["model"], "messages": messages}
    # Only pass temperature if explicitly set; some models fix temperature.
    if temperature is not None:
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)  # type: ignore
    return resp.choices[0].message.content or ""


def classify(question: str, trace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prompt = _read_prompt("classifier.txt")
    system = {
        "role": "system",
        "content": prompt,
    }
    user = {
        "role": "user",
        "content": question,
    }
    if trace is not None:
        trace["classifier"] = {"system": prompt, "user": question}
    raw = call_openai([system, user])
    try:
        return json.loads(raw)
    except Exception:
        # Fallback minimal parameters
        return {
            "keyword": question.split()[0].lower(),
            "pattern": question,
            "regex": False,
            "top_files": 8,
            "peek": True,
            "read_bytes": 0,
            "budget_tokens": 8000,
        }


def read_file_heads(file_paths: list, num_lines: int = 120) -> dict:
    """Use focus_read to get head of files for better context."""
    if not file_paths:
        return {"count": 0, "results": []}
    
    try:
        cmd = [
            sys.executable, "focus_read.py",
            "--stdin-paths", "--head", str(num_lines),
            "--json", "--quiet-missing"
        ]
        paths_input = "\n".join(str(p) for p in file_paths)
        proc = subprocess.run(
            cmd, input=paths_input, capture_output=True,
            text=True, encoding="utf-8", timeout=30
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        else:
            return {"count": 0, "results": [], "error": proc.stderr}
    except Exception as e:
        return {"count": 0, "results": [], "error": str(e)}


def read_file_heads(file_paths: list, num_lines: int = 120) -> dict:
    """Use focus_read to get head of files for better context."""
    if not file_paths:
        return {"count": 0, "results": []}
    
    try:
        cmd = [
            sys.executable, "focus_read.py",
            "--stdin-paths", "--head", str(num_lines),
            "--json", "--quiet-missing"
        ]
        paths_input = "\n".join(str(p) for p in file_paths)
        proc = subprocess.run(
            cmd, input=paths_input, capture_output=True,
            text=True, encoding="utf-8", timeout=30
        )
        if proc.returncode == 0:
            return json.loads(proc.stdout)
        else:
            return {"count": 0, "results": [], "error": proc.stderr}
    except Exception as e:
        return {"count": 0, "results": [], "error": str(e)}


def run_focus_probe(plan: dict, base: Path, verbose: bool = False) -> dict:
    """Run focus_probe with the classified plan."""
    keyword = plan.get("keyword") or ""
    if not keyword:
        keyword = "docs"
    pattern = plan.get("pattern") or ""
    if not pattern:
        pattern = keyword

    args = [
        sys.executable,
        str(Path(__file__).parent / "focus_probe.py"),
        str(keyword),
        str(pattern),
        "-b",
        str(base),
        "--json",
    ]

    if plan.get("profile"):
        args += ["--profile", str(plan["profile"])]
    if plan.get("include"):
        args += ["--include", ",".join(plan["include"])]
    if plan.get("must_parent_any"):
        args += ["--must-parent", ",".join(plan["must_parent_any"])]
    if plan.get("must_parent_all"):
        args += ["--must-parent-all", ",".join(plan["must_parent_all"])]
    if plan.get("not_parent"):
        args += ["--not-parent", ",".join(plan["not_parent"])]
    if plan.get("content_first"):
        args += ["--content-first"]
    if plan.get("regex"):
        args += ["--regex"]
    if plan.get("top_files"):
        args += ["--top-files", str(int(plan.get("top_files", 5)))]
    else:
        args += ["--top-files", "5"]  # Default to 5 for better coverage
    if plan.get("peek"):
        args += ["--peek"]
    if plan.get("read_bytes"):
        args += ["--read-bytes", str(int(plan.get("read_bytes", 0)))]
    if plan.get("budget_tokens"):
        args += ["--budget-tokens", str(int(plan.get("budget_tokens", 8000)))]

    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, text=True)
        return json.loads(out)
    except subprocess.CalledProcessError as e:
        return {"error": "probe_failed", "cmd": " ".join(shlex.quote(a) for a in args), "stdout": e.stdout}
    except json.JSONDecodeError:
        return {"error": "json_decode_failed", "cmd": " ".join(shlex.quote(a) for a in args)}


def judge(question: str, bundle_summary: str, trace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prompt = _read_prompt("judge.txt")
    system = {"role": "system", "content": prompt}
    user = {"role": "user", "content": f"Question:\n{question}\n\nProbe Summary:\n{bundle_summary}"}
    if trace is not None:
        trace["judge"] = {"system": prompt, "user": user["content"]}
    raw = call_openai([system, user])
    try:
        return json.loads(raw)
    except Exception:
        return {"sufficient": True, "confidence": 0.6, "needs_followup": False, "followup": {}}


def build_summary(bundle: Dict[str, Any], max_files: int = 8, snippets_per_file: int = 2) -> str:
    if not bundle or "error" in bundle:
        return json.dumps(bundle)
    lines: List[str] = []
    lines.append(f"Dirs: {bundle.get('dirs_found')}  Files with hits: {bundle.get('files_with_hits')}")
    clusters = bundle.get("clusters") or {}
    if clusters:
        lines.append("Clusters:")
        for k, v in list(clusters.items())[:8]:
            lines.append(f"- {k}: {len(v)}")
    lines.append("")
    for f in bundle.get("top_files", [])[:max_files]:
        lines.append(f"FILE: {f.get('path')}  (hits={f.get('hits')})")
        for sn in (f.get("snippets") or [])[:snippets_per_file]:
            lines.append(f"  [L{sn.get('line')}]")
            for c in (sn.get("context") or [])[:4]:
                lines.append(f"   {c.get('line')}: {c.get('text')}")
        lines.append("")
    return "\n".join(lines)


def answer(question: str, bundle: Dict[str, Any], trace: Optional[Dict[str, Any]] = None) -> str:
    prompt = _read_prompt("answer.txt")
    system = {"role": "system", "content": prompt}
    ctx = build_summary(bundle, max_files=8, snippets_per_file=2)
    user = {"role": "user", "content": f"Question:\n{question}\n\nCONTEXT:\n{ctx}"}
    if trace is not None:
        trace["answer"] = {"system": prompt, "user": user["content"]}
    return call_openai([system, user])


def _rule_based_plan(question: str) -> Dict[str, Any]:
    q = question.lower()
    plan: Dict[str, Any] = {
        "keyword": "docs",
        "pattern": question,
        "regex": False,
        "include": ["*.md", "*.rst", "*.py"],
        "must_parent_any": ["src", "ws"],
        "not_parent": ["tests", "examples", "archived"],
        "top_files": 8,
        "peek": True,
        "read_bytes": 0,
        "budget_tokens": 8000,
    }
    if any(k in q for k in ["teleop", "rviz", "launch", "ros2 launch"]):
        plan.update({
            "keyword": "spot" if "spot" in q else "ros",
            "pattern": "(teleop|rviz|launch|cmd_vel)",
            "regex": True,
            "include": ["*.launch.py", "*.md", "*.py"],
        })
    elif any(k in q for k in ["message", "msg", "interface", "srv", "idl"]):
        plan.update({
            "keyword": "msg",
            "include": ["*.msg", "*.idl", "*.srv", "*.md"],
        })
    return plan


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("Usage: python focus_llm.py \"Question...\" -b BASE [--verbose] [--dry-run]", file=sys.stderr)
        return 2
    # Simple CLI parse (robust question capture with spaces)
    # Collect tokens until we hit a known flag like -b or --dry-run
    q_tokens: List[str] = []
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in ("-b", "--dry-run", "--verbose") or tok.startswith("--"):
            break
        q_tokens.append(tok)
        i += 1
    question = " ".join(q_tokens).strip() or (argv[1] if len(argv) > 1 else "")
    try:
        bidx = argv.index("-b")
        base = Path(argv[bidx + 1]).expanduser().resolve()
    except ValueError:
        base = Path(".").resolve()

    # Optional dry-run mode to print payloads without calling LLM
    dry = "--dry-run" in argv
    # Optional verbose mode to print intermediate steps
    verbose = "--verbose" in argv
    # Optional trace dump
    trace_out: Optional[str] = None
    if "--trace-out" in argv:
        try:
            tidx = argv.index("--trace-out")
            trace_out = argv[tidx + 1]
        except Exception:
            trace_out = None
    trace: Dict[str, Any] = {}

    # 1) classify or rule-based
    if verbose:
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 1: CLASSIFY", file=sys.stderr)
        print("="*80, file=sys.stderr)
    plan1 = classify(question, trace=trace) if not dry else _rule_based_plan(question)
    if verbose:
        print(f"Question: {question}", file=sys.stderr)
        print(f"Plan: {json.dumps(plan1, indent=2)}", file=sys.stderr)
    
    # 2) probe
    if verbose:
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 2: PROBE", file=sys.stderr)
        print("="*80, file=sys.stderr)
    bundle1 = run_focus_probe(plan1, base)
    if "error" in bundle1:
        print(json.dumps(bundle1, indent=2))
        return 1
    if verbose:
        print(f"Dirs found: {bundle1.get('dirs_found', 0)}", file=sys.stderr)
        print(f"Files scanned: {bundle1.get('files_scanned', 0)}", file=sys.stderr)
        print(f"Files with hits: {bundle1.get('files_with_hits', 0)}", file=sys.stderr)
        print(f"Top files: {len(bundle1.get('top_files', []))}", file=sys.stderr)
        if bundle1.get('top_files'):
            print("\nTop 3 files:", file=sys.stderr)
            for f in bundle1.get('top_files', [])[:3]:
                print(f"  - {f.get('path')} (hits={f.get('hits')})", file=sys.stderr)
    
    # 3) judge
    summary1 = build_summary(bundle1)
    if verbose:
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 3: JUDGE", file=sys.stderr)
        print("="*80, file=sys.stderr)
        print(f"Summary preview:\n{summary1[:500]}...", file=sys.stderr)
    if dry:
        # Print the messages that would be sent to LLMs and exit
        print("=== CLASSIFIER: system ===\n")
        print(_read_prompt("classifier.txt")[:1200])
        print("\n=== CLASSIFIER: user ===\n")
        print(question)

        print("\n=== JUDGE: system ===\n")
        print(_read_prompt("judge.txt")[:1200])
        print("\n=== JUDGE: user ===\n")
        print(f"Question:\n{question}\n\nProbe Summary (truncated):\n{summary1[:4000]}")

        print("\n=== ANSWER: system ===\n")
        print(_read_prompt("answer.txt")[:1200])
        print("\n=== ANSWER: user ===\n")
        ctx = build_summary(bundle1, max_files=8, snippets_per_file=2)
        print(f"Question:\n{question}\n\nCONTEXT (truncated):\n{ctx[:4000]}")
        return 0

    verdict1 = judge(question, summary1, trace=trace) if not dry else {"sufficient": True}
    if verbose:
        print(f"Verdict: {json.dumps(verdict1, indent=2)}", file=sys.stderr)
    
    if verdict1.get("sufficient"):
        if verbose:
            print("\n" + "="*80, file=sys.stderr)
            print("STEP 4: ANSWER", file=sys.stderr)
            print("="*80, file=sys.stderr)
        out = answer(question, bundle1, trace=trace) if not dry else ""
        print(out)
        if trace_out:
            Path(trace_out).write_text(json.dumps(trace, indent=2), encoding="utf-8")
        return 0

    # bounded follow-up (one more try)
    if verbose:
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 3B: FOLLOW-UP PROBE", file=sys.stderr)
        print("="*80, file=sys.stderr)
    
    follow = verdict1.get("followup") or {}
    # allow pattern augment
    add_patterns = follow.get("add_patterns") or []
    if add_patterns:
        pat = plan1.get("pattern") or question
        plan1["pattern"] = "|".join([pat] + add_patterns)
        plan1["regex"] = True
    # allow narrowing to specific dirs via must_parent_any
    narrow = follow.get("narrow_to_paths") or []
    if narrow:
        # Convert absolute paths into parent tokens
        tokens: List[str] = []
        for p in narrow:
            parts = Path(p).parts
            tokens.extend([x for x in parts[-3:]])
        if tokens:
            plan1["must_parent_any"] = list({t for t in tokens if t})

    if verbose:
        print(f"Refined plan: {json.dumps(plan1, indent=2)}", file=sys.stderr)

    bundle2 = run_focus_probe(plan1, base)
    if verbose:
        print(f"Follow-up results:", file=sys.stderr)
        print(f"  Dirs found: {bundle2.get('dirs_found', 0)}", file=sys.stderr)
        print(f"  Files with hits: {bundle2.get('files_with_hits', 0)}", file=sys.stderr)
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 4: ANSWER", file=sys.stderr)
        print("="*80, file=sys.stderr)
    
    out = answer(question, bundle2, trace=trace) if not dry else ""
    print(out)
    if trace_out:
        Path(trace_out).write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
