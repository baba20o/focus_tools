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


def _get_env_models() -> Dict[str, str]:
    """Return {'main': model, 'mini': mini_model or model} from env."""
    base = _require_env()
    main = base["model"].strip()
    mini = os.getenv("OPENAI_MINI_MODEL", "").strip() or main
    return {"main": main, "mini": mini}


def call_openai(messages: List[Dict[str, str]], *, temperature: Optional[float] = None, model: Optional[str] = None, debug: bool = False, label: str = "") -> str:
    """Minimal OpenAI Chat Completions call. If model is None, uses OPENAI_MODEL."""
    creds = _require_env()
    try:
        from openai import OpenAI  # type: ignore
    except Exception:
        raise SystemExit("Install openai>=1.0: pip install openai")

    client = OpenAI(api_key=creds["api_key"])  # type: ignore
    use_model = model or creds["model"]
    kwargs: Dict[str, Any] = {"model": use_model, "messages": messages}
    # Only pass temperature if explicitly set; some models fix temperature.
    if temperature is not None:
        kwargs["temperature"] = temperature
    if debug:
        sys.stderr.write(f"\n=== LLM CALL [{label or 'unknown'}] model={use_model} ===\n")
        for m in messages:
            role = m.get("role","?")
            sys.stderr.write(f"--- {role} ---\n{m.get('content','')}\n")
        sys.stderr.write("=== END INPUT ===\n")
    resp = client.chat.completions.create(**kwargs)  # type: ignore
    out = resp.choices[0].message.content or ""
    if debug:
        sys.stderr.write(f"\n=== LLM OUTPUT [{label or 'unknown'}] ===\n{out}\n=== END OUTPUT ===\n")
    return out


def classify(question: str, trace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # Allow disabling mini LLM usage entirely
    if os.getenv("FOCUS_USE_MINI", "0").strip() not in ("1", "true", "True"):
        return _rule_based_plan(question)
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
    models = _get_env_models()
    debug = os.getenv("FOCUS_DEBUG_LLM", "0").strip() in ("1","true","True")
    raw = call_openai([system, user], model=models["mini"], debug=debug, label="classify")
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


def run_focus_probe(plan: dict, bases: List[Path], verbose: bool = False) -> dict:
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
        "--json",
    ]
    for b in bases:
        args += ["-b", str(b)]

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
    if plan.get("file_name_globs"):
        args += ["--file-name-globs", ",".join(plan.get("file_name_globs", []))]
        args += ["--include-all"]

    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, text=True)
        return json.loads(out)
    except subprocess.CalledProcessError as e:
        return {"error": "probe_failed", "cmd": " ".join(shlex.quote(a) for a in args), "stdout": e.stdout}
    except json.JSONDecodeError:
        return {"error": "json_decode_failed", "cmd": " ".join(shlex.quote(a) for a in args)}


def judge(question: str, bundle_summary: str, trace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    # If mini usage is disabled, default to sufficient
    if os.getenv("FOCUS_USE_MINI", "0").strip() not in ("1", "true", "True"):
        return {"sufficient": True, "confidence": 0.6, "needs_followup": False, "followup": {}}
    prompt = _read_prompt("judge.txt")
    system = {"role": "system", "content": prompt}
    user = {"role": "user", "content": f"Question:\n{question}\n\nProbe Summary:\n{bundle_summary}"}
    if trace is not None:
        trace["judge"] = {"system": prompt, "user": user["content"]}
    models = _get_env_models()
    debug = os.getenv("FOCUS_DEBUG_LLM", "0").strip() in ("1","true","True")
    raw = call_openai([system, user], model=models["mini"], debug=debug, label="judge")
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
        # Include extractions when available
        if f.get('extracted_msg_fields'):
            lines.append("  MSG FIELDS:")
            for fld in f.get('extracted_msg_fields', [])[:10]:
                lines.append(f"    - {fld}")
        if f.get('extracted_urdf_joints'):
            lines.append("  URDF JOINTS:")
            for j in f.get('extracted_urdf_joints', [])[:10]:
                lines.append(f"    - {j}")
        if f.get('extracted_msg_nested'):
            lines.append("  NESTED MSGS:")
            nested = f.get('extracted_msg_nested', {})
            for t, fields in list(nested.items())[:3]:
                lines.append(f"    {t}:")
                for fld in fields[:6]:
                    lines.append(f"      - {fld}")
        if f.get('extracted_symbol'):
            sym = f.get('extracted_symbol', {})
            lines.append(f"  SYMBOL {sym.get('name','')}:\n")
            for ln in sym.get('block', [])[:12]:
                lines.append(f"    {ln.get('line')}: {ln.get('text')}")
        for sn in (f.get("snippets") or [])[:snippets_per_file]:
            lines.append(f"  [L{sn.get('line')}]")
            for c in (sn.get("context") or [])[:4]:
                lines.append(f"   {c.get('line')}: {c.get('text')}")
        lines.append("")
    # Bundle-level symbols (cross-file)
    syms = bundle.get('symbols') or []
    if syms:
        lines.append("SYMBOLS:")
        for s in syms[:2]:
            lines.append(f"- {s.get('name','')} in {s.get('path','')}")
            for ln in s.get('block', [])[:8]:
                lines.append(f"   {ln.get('line')}: {ln.get('text')}")
            lines.append("")
    # Optional RAG chunks (scoped semantic retrieval)
    rchunks = bundle.get('rag_chunks') or []
    if rchunks:
        lines.append("RAG CHUNKS:")
        for c in rchunks[:3]:
            url = c.get('url', '')
            text = (c.get('text', '') or '')[:240].replace('\n', ' ')
            score = c.get('score')
            lines.append(f"- {url}  (score={score})")
            if text:
                lines.append(f"  {text}")
        lines.append("")
    return "\n".join(lines)


def _infer_category(question: str) -> str:
    q = (question or "").lower()
    if any(k in q for k in ["stand for", "acronym", "definition", "what is"]):
        return "definition"
    if any(k in q for k in ["message", "msg", "srv", "idl", "fields"]):
        return "schema"
    if any(k in q for k in ["config", "parameter", "launch", "pyproject", "dockerfile", "toml"]):
        return "config"
    if any(k in q for k in ["wave()", "function", "symbol", "how does", "calculate", "controller"]):
        return "symbol"
    if any(k in q for k in ["troubleshoot", "error", "timeout", "deadlock", "issue", "not working", "puzzling"]):
        return "troubleshooting"
    if any(k in q for k in ["best practice", "how to", "guidelines", "examples"]):
        return "docs_guidelines"
    return "general"


def _load_router_policy() -> Dict[str, Any]:
    # Optional JSON policy
    for cand in [Path("docs/router_policy.json"), Path("router_policy.json")]:
        if cand.exists():
            try:
                return json.loads(cand.read_text(encoding="utf-8"))
            except Exception:
                return {}
    return {}


def answer(question: str, bundle: Dict[str, Any], trace: Optional[Dict[str, Any]] = None) -> str:
    prompt = _read_prompt("answer.txt")
    system = {"role": "system", "content": prompt}
    ctx = build_summary(bundle, max_files=8, snippets_per_file=2)
    user = {"role": "user", "content": f"Question:\n{question}\n\nCONTEXT:\n{ctx}"}
    if trace is not None:
        trace["answer"] = {"system": prompt, "user": user["content"]}
    models = _get_env_models()
    debug = os.getenv("FOCUS_DEBUG_LLM", "0").strip() in ("1","true","True")
    return call_openai([system, user], model=models["main"], debug=debug, label="answer")


def mini_rescore(question: str, file_heads: dict) -> List[Dict[str, Any]]:
    """Use a small model to rescore relevance of file heads.
    Returns a list of {path, mini_score, type}.
    """
    models = _get_env_models()
    out: List[Dict[str, Any]] = []
    for f in file_heads.get("results", []):
        if f.get("error"):
            continue
        path = f.get("path", "")
        lines = f.get("content", [])
        head_text = "\n".join(ln.get("text", "") for ln in lines[:50])
        system = {"role": "system", "content": "Rank file relevance for answering the question. JSON only."}
        content = (
            'Return strict JSON: {"score": 0.0-1.0, "type": "definitive|mentions|unrelated"}.\n'
            f"Question: {question}\nFile: {path}\nPreview:\n{head_text}"
        )
        user = {"role": "user", "content": content}
        try:
            # Some models do not support setting temperature; omit it here.
            raw = call_openai([system, user], model=models["mini"], debug=os.getenv("FOCUS_DEBUG_LLM","0").strip() in ("1","true","True"), label="rescore")
            data = json.loads(raw)
            score = float(data.get("score", 0.0))
            typ = str(data.get("type", "unknown"))
            out.append({"path": path, "mini_score": score, "type": typ})
        except Exception as e:
            out.append({"path": path, "mini_score": 0.5, "type": "error", "error": str(e)})
    return out


def _add_filename_globs_by_intent(question: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    q = (question or "").lower()
    globs: List[str] = list(plan.get("file_name_globs") or [])
    # Robot action style questions
    if "robot action" in q and "robot_actions.py" not in globs:
        globs.append("robot_actions.py")
    # Build/dependency style questions
    if ("python package" in q or "dependency" in q or "pyproject" in q) and "pyproject.toml" not in globs:
        globs.extend(["pyproject.toml", "Dockerfile*"])
    # Symbol questions: leave to content grep (no specific filename), but could add patterns later
    if globs:
        plan["file_name_globs"] = sorted(set(globs))
    return plan


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
    # Collect all base paths (repeatable -b)
    bases: List[Path] = []
    i2 = 1
    while i2 < len(argv):
        if argv[i2] == "-b" and (i2 + 1) < len(argv):
            bases.append(Path(argv[i2 + 1]).expanduser().resolve())
            i2 += 2
        else:
            i2 += 1
    if not bases:
        bases = [Path(".").resolve()]

    # Optional dry-run mode to print payloads without calling LLM
    dry = "--dry-run" in argv
    # Optional verbose mode to print intermediate steps
    verbose = "--verbose" in argv
    allow_rag_flag = "--allow-rag" in argv
    # Optional router overrides
    router_mode_cli: Optional[str] = None
    rag_sources_cli: Optional[List[str]] = None
    if "--router-mode" in argv:
        try:
            router_mode_cli = argv[argv.index("--router-mode") + 1].strip()
        except Exception:
            router_mode_cli = None
    if "--rag-sources" in argv:
        try:
            rag_sources_cli = [s.strip() for s in argv[argv.index("--rag-sources") + 1].split(",") if s.strip()]
        except Exception:
            rag_sources_cli = None
    debug_llm = "--debug-llm" in argv
    # Optional trace dump
    trace_out: Optional[str] = None
    if "--trace-out" in argv:
        try:
            tidx = argv.index("--trace-out")
            trace_out = argv[tidx + 1]
        except Exception:
            trace_out = None
    trace: Dict[str, Any] = {}
    # propagate debug to child calls via env flag
    if debug_llm:
        os.environ["FOCUS_DEBUG_LLM"] = "1"

    # 1) classify or rule-based
    if verbose:
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 1: CLASSIFY", file=sys.stderr)
        print("="*80, file=sys.stderr)
    plan1 = classify(question, trace=trace) if not dry else _rule_based_plan(question)
    # Enrich plan with filename globs by intent (works for both rule-based and LLM plans)
    plan1 = _add_filename_globs_by_intent(question, plan1)
    if verbose:
        print(f"Question: {question}", file=sys.stderr)
        print(f"Plan: {json.dumps(plan1, indent=2)}", file=sys.stderr)
    
    # 2) probe
    if verbose:
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 2: PROBE", file=sys.stderr)
        print("="*80, file=sys.stderr)
    bundle1 = run_focus_probe(plan1, bases)
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

    # 2b) Optional mini-LLM rescoring (disabled unless FOCUS_USE_MINI=1)
    if os.getenv("FOCUS_USE_MINI", "0").strip() in ("1", "true", "True"):
        top_paths = [f.get("path") for f in bundle1.get("top_files", []) if f.get("path")]
        if top_paths:
            heads = read_file_heads(top_paths, num_lines=120)
            rescored = mini_rescore(question, heads)
            if trace is not None:
                trace["rescore"] = rescored
            # Combine probe rank with mini score: 60/40 weighting
            rank_n = len(top_paths)
            probe_rank: Dict[str, float] = {}
            for idx, p in enumerate(top_paths, start=1):
                probe_rank[p] = 1.0 - (idx - 1) / max(1, rank_n)
            mini_map = {e["path"]: float(e.get("mini_score", 0.5)) for e in rescored}
            def final_score(entry: Dict[str, Any]) -> float:
                p = entry.get("path", "")
                return 0.6 * probe_rank.get(p, 0.5) + 0.4 * mini_map.get(p, 0.5)
            bundle1["top_files"] = sorted(bundle1.get("top_files", []), key=final_score, reverse=True)
    
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

    bundle2 = run_focus_probe(plan1, bases)
    
    # Choose best of initial vs follow-up bundles to avoid regressions
    def _bundle_score(b: Dict[str, Any]) -> float:
        if not b:
            return 0.0
        fwh = float(b.get('files_with_hits', 0) or 0)
        tf = b.get('top_files') or []
        # Count authority files in top files by suffix
        auth_ext = {'.msg', '.idl', '.srv', '.urdf', '.xacro'}
        auth_count = 0
        extracted_bonus = 0
        for f in tf:
            p = str(f.get('path','')).lower()
            for ext in auth_ext:
                if p.endswith(ext):
                    auth_count += 1
                    break
            if f.get('extracted_msg_fields') or f.get('extracted_urdf_joints'):
                extracted_bonus += 1
        # files_with_hits dominates; authority and extraction nudge score
        return fwh + 0.3*auth_count + 0.2*extracted_bonus + 0.05*len(tf)

    better = bundle2 if _bundle_score(bundle2) >= _bundle_score(bundle1) else bundle1

    # Optional scoped RAG fallback (import-based adapter), guarded by env/flag and router policy
    allow_rag_env = os.getenv("ALLOW_RAG", "0").strip() in ("1", "true", "True")
    policy = _load_router_policy()
    category = _infer_category(question)
    pol = policy.get(category, {}) if isinstance(policy, dict) else {}
    pol_allow = bool(pol.get("allow_rag", False))
    pol_sources = pol.get("source_types") if isinstance(pol.get("source_types"), list) else None
    router_mode = (router_mode_cli or pol.get("router_mode") or "auto").lower()
    if rag_sources_cli:
        pol_sources = rag_sources_cli
        pol_allow = True
    if verbose:
        print(f"Router category: {category}; mode={router_mode}; policy_allow={pol_allow}; sources={pol_sources}", file=sys.stderr)
    allow_by_mode = (
        (router_mode == "policy" and pol_allow) or
        (router_mode == "router" and True) or
        (router_mode == "auto" and (pol_allow or category in ("troubleshooting", "docs_guidelines")))
    )
    if (allow_rag_env or allow_rag_flag) and allow_by_mode:
        try:
            from focus_rag_adapter import rag_search  # type: ignore
            # Heuristic trigger: escalate when focus evidence is weak, or low authority for tricky categories
            fwh = int(better.get("files_with_hits", 0) or 0)
            tf = better.get("top_files") or []
            auth_ext = {'.msg', '.idl', '.srv', '.urdf', '.xacro', '.launch.py'}
            auth_count = 0
            extract_signals = 0
            for f in tf:
                p = str(f.get('path','')).lower()
                if any(p.endswith(ext) for ext in auth_ext):
                    auth_count += 1
                if f.get('extracted_msg_fields') or f.get('extracted_urdf_joints') or f.get('extracted_symbol'):
                    extract_signals += 1
            weak_focus = fwh < 3
            low_auth_for_help = (category in ("troubleshooting","docs_guidelines") and (auth_count == 0 and extract_signals == 0) and fwh < 5)
            scope = list(better.get("path_prefixes") or [])
            if weak_focus or low_auth_for_help or router_mode == "router":
                rdocs = rag_search(question, path_filters=scope, k=5, debug=verbose, source_types=pol_sources)
                if rdocs:
                    better["rag_chunks"] = rdocs
                    if verbose:
                        print(f"Added {len(rdocs)} RAG chunks (scoped) to bundle", file=sys.stderr)
        except Exception as e:
            if verbose:
                print(f"RAG adapter not available or failed: {e}", file=sys.stderr)

    if verbose:
        print(f"Follow-up results:", file=sys.stderr)
        print(f"  Dirs found: {bundle2.get('dirs_found', 0)}", file=sys.stderr)
        print(f"  Files with hits: {bundle2.get('files_with_hits', 0)}", file=sys.stderr)
        print("\n" + "="*80, file=sys.stderr)
        print("STEP 4: ANSWER", file=sys.stderr)
        print("="*80, file=sys.stderr)
    
    out = answer(question, better, trace=trace) if not dry else ""
    print(out)
    if trace_out:
        Path(trace_out).write_text(json.dumps(trace, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
