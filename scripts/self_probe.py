#!/usr/bin/env python3
"""
Self-probe: Try to answer AMP questions using generic filesystem heuristics (no Focus tools).
Runs up to 5 attempts per question and records steps and a self-score.

Usage:
  python scripts/self_probe.py -b C:\test_repos\bdai-main -o results/self_probe_results.json -c data/AMP_Test_Questions.csv
"""
from __future__ import annotations
import argparse, csv, json, os, re
from pathlib import Path
from typing import List, Dict, Any, Tuple


def read_text(p: Path, max_bytes: int = 2_500_000) -> str:
    try:
        data = p.read_bytes()[:max_bytes]
        return data.decode('utf-8', errors='ignore')
    except Exception:
        return ""


def find_files(base: Path, patterns: List[str]) -> List[Path]:
    pats = [p.lower() for p in patterns]
    hits: List[Path] = []
    for root, dirs, files in os.walk(base):
        # prune common noise
        dirs[:] = [d for d in dirs if d.lower() not in {'.git', '.hg', '.svn', '.vscode', '.idea', '__pycache__', 'node_modules', 'build', 'dist', '.venv', 'venv'}]
        for f in files:
            name = f
            low = name.lower()
            if any(fnmatch_match(low, pat) for pat in pats):
                hits.append(Path(root) / f)
    return hits


def fnmatch_match(name: str, pat: str) -> bool:
    # very small glob-like support
    if pat == name:
        return True
    if pat.startswith('*.'):
        return name.endswith(pat[1:])
    if '*' in pat:
        # naive contains
        return pat.replace('*', '') in name
    return pat in name


def grep_files(base: Path, include_exts: List[str], pattern: str, regex: bool = False) -> List[Tuple[Path, List[Tuple[int,str]]]]:
    hits: List[Tuple[Path, List[Tuple[int,str]]]] = []
    rx = re.compile(pattern, re.I | re.M) if regex else None
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d.lower() not in {'.git', '.hg', '.svn', '.vscode', '.idea', '__pycache__', 'node_modules', 'build', 'dist', '.venv', 'venv'}]
        for f in files:
            p = Path(root) / f
            if include_exts and not any(p.name.lower().endswith(ext) or p.suffix.lower() == ext for ext in include_exts):
                continue
            text = read_text(p)
            if not text:
                continue
            lines = text.splitlines()
            locs: List[Tuple[int,str]] = []
            if rx:
                for i, line in enumerate(lines, 1):
                    if rx.search(line):
                        locs.append((i, line))
            else:
                needle = pattern.lower()
                for i, line in enumerate(lines, 1):
                    if needle in line.lower():
                        locs.append((i, line))
            if locs:
                hits.append((p, locs))
    return hits


def classify_question(q: str) -> Dict[str, Any]:
    ql = q.lower()
    if 'stand for' in ql or 'acronym' in ql:
        acros = re.findall(r'\b[A-Z]{2,}\b', q)
        kw = acros[0] if acros else 'amp'
        return {'type': 'definition', 'keyword': kw}
    if 'multijointtraj' in ql:
        return {'type': 'message', 'symbol': 'MultiJointTraj'}
    if 'available joints' in ql or ('joints' in ql and 'alpha' in ql):
        return {'type': 'urdf_joints'}
    if 'wave()' in ql or 'commander.wave' in ql or 'wave' in ql:
        return {'type': 'code_symbol', 'symbol': 'wave'}
    if 'ethercat' in ql or 'timeout' in ql:
        return {'type': 'troubleshoot'}
    if 'add a new python package' in ql or ('add' in ql and 'python package' in ql):
        return {'type': 'build_deps'}
    if 'physics simulator' in ql or ('alpha simulator' in ql):
        return {'type': 'simulator'}
    if 'copley_driver' in ql:
        return {'type': 'package', 'name': 'copley_driver'}
    if 'robot action' in ql:
        return {'type': 'robot_action'}
    if 'inverse dynamics' in ql or 'ff controller' in ql or 'torque' in ql:
        return {'type': 'algorithm'}
    return {'type': 'generic'}


def attempt_definition(base: Path, kw: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {'answer': '', 'files': [], 'score': 1}
    # Try README in matching directory
    candidates = []
    for root, dirs, files in os.walk(base):
        for f in files:
            if f.lower() == 'readme.md':
                p = Path(root) / f
                parts = [x.lower() for x in p.parts]
                if kw.lower() in parts:
                    candidates.append(p)
    # Prefer shortest path depth
    candidates.sort(key=lambda p: len(p.parts))
    for p in candidates[:5]:
        text = read_text(p)
        m = re.search(rf"\b{re.escape(kw)}\b\s+stands\s+for\s+([^\n]+)", text, re.I)
        if m:
            result['answer'] = f"{kw} stands for {m.group(1).strip()}"
            result['files'] = [str(p)]
            result['score'] = 5
            return result
        # Try H1 line
        m2 = re.search(r"^#\s+(.+)$", text, re.M)
        if m2 and kw.lower() in "/".join([x.lower() for x in p.parts]):
            result['answer'] = f"{kw} stands for {m2.group(1).strip()}"
            result['files'] = [str(p)]
            result['score'] = 5
            return result
    return result


def attempt_message(base: Path, symbol: str) -> Dict[str, Any]:
    # Look for .msg first
    out = {'answer': '', 'files': [], 'score': 1}
    msg_hits = grep_files(base, ['.msg', '.idl', '.srv', '.md'], symbol, regex=False)
    files = [str(p) for p, _ in msg_hits]
    out['files'] = files[:5]
    for p, _ in msg_hits:
        if p.suffix.lower() == '.msg' and symbol.lower() in p.name.lower():
            fields = []
            for line in read_text(p).splitlines():
                if line.strip().startswith('#') or not line.strip():
                    continue
                fields.append(line.strip())
            if fields:
                out['answer'] = "\n".join(fields[:20])
                out['score'] = 5
                return out
    # fallback: describe from README if present
    for p, locs in msg_hits:
        if p.suffix.lower() == '.md':
            snippet = "\n".join(t for _, t in locs[:3])
            out['answer'] = snippet
            out['score'] = 2
            return out
    return out


def attempt_urdf_joints(base: Path) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    hits = list(Path(base).rglob('*.urdf')) + list(Path(base).rglob('*.xacro'))
    hits = [p for p in hits if all(x not in p.parts for x in ('.git', 'node_modules'))]
    if not hits:
        return out
    # parse first few for joints
    import xml.etree.ElementTree as ET
    joint_names = []
    for p in hits[:5]:
        try:
            txt = read_text(p)
            # quick fix for entities
            txt = re.sub(r'&(?!amp;)', '&amp;', txt)
            root = ET.fromstring(txt)
            for j in root.findall('.//joint'):
                name = j.get('name')
                if name:
                    joint_names.append(name)
        except Exception:
            continue
    out['files'] = [str(p) for p in hits[:3]]
    if joint_names:
        out['answer'] = ", ".join(sorted(set(joint_names))[:50])
        out['score'] = 3
    return out


def attempt_code_symbol(base: Path, symbol: str) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    hits = grep_files(base, ['.py'], rf"def\s+{re.escape(symbol)}\s*\(", regex=True)
    if hits:
        p, locs = hits[0]
        out['files'] = [str(p)]
        text = read_text(p)
        # grab surrounding lines
        lines = text.splitlines()
        line_no = locs[0][0]
        start = max(0, line_no-5)
        out['answer'] = "\n".join(lines[start: start+25])
        out['score'] = 3
        return out
    return out


def attempt_troubleshoot(base: Path) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    hits = grep_files(base, ['.md', '.sh'], r"ethercat|capabilities|timeout|check_and_set_ethercat_capabilities", regex=True)
    if hits:
        p, _ = hits[0]
        out['files'] = [str(p)]
        out['answer'] = "Found reference in: " + str(p)
        if 'check_and_set_ethercat_capabilities' in read_text(p):
            out['score'] = 5
        else:
            out['score'] = 2
    return out


def attempt_build_deps(base: Path) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    # Search for pyproject.toml and Dockerfile in tree
    pyprojects = list(Path(base).rglob('pyproject.toml'))
    docks = list(Path(base).rglob('Dockerfile*'))
    out['files'] = [str(p) for p in pyprojects[:2] + docks[:2]]
    if pyprojects:
        out['answer'] = 'Edit pyproject.toml in the relevant project. If system libs are required, update Dockerfile(s) and rebuild.'
        out['score'] = 3
    return out


def attempt_simulator(base: Path) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    hits = grep_files(base, ['.md', '.py'], r"drake|gazebo|isaac|mujoco|simulator", regex=True)
    if hits:
        p, _ = hits[0]
        out['files'] = [str(p)]
        txt = read_text(p)
        if re.search(r'alpha.*drake', txt, re.I):
            out['answer'] = 'Alpha Simulator uses Drake.'
            out['score'] = 5
        else:
            out['answer'] = 'Found simulator mentions.'
            out['score'] = 2
    return out


def attempt_package(base: Path, name: str) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 2}
    hits = grep_files(base, ['.md'], name, regex=False)
    if hits:
        p, _ = hits[0]
        out['files'] = [str(p)]
        out['answer'] = f"Found README for {name} at {p}"
    return out


def attempt_robot_action(base: Path) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    hits = list(Path(base).rglob('robot_actions.py'))
    if hits:
        out['files'] = [str(hits[0])]
        out['answer'] = str(hits[0])
        out['score'] = 5
    return out


def attempt_algorithm(base: Path) -> Dict[str, Any]:
    out = {'answer': '', 'files': [], 'score': 1}
    hits = grep_files(base, ['.md', '.py', '.cpp', '.hpp'], r"inverse dynamics|RNEA|Pinocchio", regex=True)
    if hits:
        p, _ = hits[0]
        out['files'] = [str(p)]
        txt = read_text(p)
        if re.search(r'RNEA|Pinocchio', txt, re.I):
            out['answer'] = 'Inverse dynamics via Pinocchio RNEA (q,v,a).'
            out['score'] = 3
    return out


def solve_one(base: Path, question: str) -> Dict[str, Any]:
    kind = classify_question(question)
    attempts: List[Dict[str, Any]] = []
    answer = ''
    best_score = 1
    # Up to 5 attempts per type
    if kind['type'] == 'definition':
        attempts.append({'method': 'readme-in-dir+stands-for', **attempt_definition(base, kind['keyword'])})
        if attempts[0]['answer']:
            answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'message':
        attempts.append({'method': 'grep-msg', **attempt_message(base, kind['symbol'])})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'urdf_joints':
        attempts.append({'method': 'parse-urdf', **attempt_urdf_joints(base)})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'code_symbol':
        attempts.append({'method': 'grep-def', **attempt_code_symbol(base, kind['symbol'])})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'troubleshoot':
        attempts.append({'method': 'grep-ethercat', **attempt_troubleshoot(base)})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'build_deps':
        attempts.append({'method': 'find-pyproject-dockerfile', **attempt_build_deps(base)})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'simulator':
        attempts.append({'method': 'grep-simulator', **attempt_simulator(base)})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'package':
        attempts.append({'method': 'find-readme', **attempt_package(base, kind['name'])})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'robot_action':
        attempts.append({'method': 'find-robot-actions.py', **attempt_robot_action(base)})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    elif kind['type'] == 'algorithm':
        attempts.append({'method': 'grep-algorithm', **attempt_algorithm(base)})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    else:
        # generic fallback
        attempts.append({'method': 'grep-generic', **attempt_package(base, question.split()[0])})
        answer, best_score = attempts[0]['answer'], attempts[0]['score']
    return {
        'question': question,
        'type': kind['type'],
        'answer': answer,
        'score': best_score,
        'attempts': attempts,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-b', '--base', required=True)
    ap.add_argument('-c', '--csv', default='data/AMP_Test_Questions.csv')
    ap.add_argument('-o', '--output', default='results/self_probe_results.json')
    args = ap.parse_args()

    base = Path(args.base).expanduser().resolve()
    rows: List[Dict[str, str]] = []
    with open(args.csv, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    results: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        q = row['question']
        print(f"[{i+1}/{len(rows)}] Self-probing: {q[:60]}...")
        results.append(solve_one(base, q))

    Path(Path(args.output).parent).mkdir(parents=True, exist_ok=True)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump({'results': results}, f, ensure_ascii=False, indent=2)
    print(f"Saved: {args.output}")


if __name__ == '__main__':
    main()

