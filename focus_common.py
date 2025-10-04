#!/usr/bin/env python3
# file: focus_common.py
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional, Iterable, Union
import json
import os
import sys
import re

try:
    import yaml  # type: ignore
    _YAML_OK = True
except Exception:
    _YAML_OK = False

# ---------- Utilities ----------

def normalize(s: str) -> str:
    return s.strip().lower().replace("-", "_")

def parse_csv_list(val: Union[str, Iterable[str], None]) -> List[str]:
    if val is None:
        return []
    if isinstance(val, str):
        items = [p.strip() for p in val.split(",") if p.strip()]
        return items
    out: List[str] = []
    for item in val:
        if not item:
            continue
        out.extend([p.strip() for p in str(item).split(",") if p.strip()])
    return out

def is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False

# ---------- Color (ANSI) ----------

class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

def colorize(s: str, *styles: str, enable: bool = True) -> str:
    if not enable:
        return s
    seq = "".join(styles)
    end = Ansi.RESET if seq else ""
    return f"{seq}{s}{end}"

# ---------- Config / Profiles ----------

DEFAULT_CONFIG_PATHS = [
    "~/.focus_config.yaml",   # user-wide
]

@dataclass
class FocusConfig:
    aliases: Dict[str, List[str]] = field(default_factory=dict)
    defaults: Dict[str, Any] = field(default_factory=dict)
    weights: Dict[str, float] = field(default_factory=dict)  # suffix -> weight
    profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)

def _load_yaml_file(p: Path) -> Dict[str, Any]:
    if not _YAML_OK:
        return {}
    try:
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        return {}
    return {}

def load_config(extra_paths: Optional[List[Path]] = None) -> FocusConfig:
    paths: List[Path] = [Path(os.path.expanduser(p)) for p in DEFAULT_CONFIG_PATHS]
    if extra_paths:
        paths.extend(extra_paths)

    merged: Dict[str, Any] = {}
    for p in paths:
        data = _load_yaml_file(p)
        if not data:
            continue
        # shallow merge per top-level key
        for k, v in data.items():
            if isinstance(v, dict):
                merged.setdefault(k, {})
                merged[k].update(v)
            else:
                merged[k] = v

    cfg = FocusConfig(
        aliases=merged.get("aliases", {}) or {},
        defaults=merged.get("defaults", {}) or {},
        weights=merged.get("weights", {}) or {},
        profiles=merged.get("profiles", {}) or {},
    )
    return cfg

def expand_aliases(keyword: str, alias_map: Dict[str, List[str]]) -> List[str]:
    k = normalize(keyword)
    aliases = set([k])
    for key, vals in alias_map.items():
        nkey = normalize(key)
        nvals = [normalize(v) for v in vals]
        if k == nkey or k in nvals:
            aliases.add(nkey)
            aliases.update(nvals)
    return sorted(aliases)

def apply_profile(base_kwargs: Dict[str, Any], cfg: FocusConfig, profile_name: Optional[str]) -> Dict[str, Any]:
    """
    Merge a profile onto base kwargs. CLI args should already be parsed into base_kwargs.
    CLI wins; only fill missing fields from profile.
    """
    if not profile_name:
        return base_kwargs
    prof = cfg.profiles.get(profile_name)
    if not prof:
        return base_kwargs

    # Expand CSV-ish strings in profile to lists for common fields
    prof = dict(prof)  # shallow copy
    for key in ["include", "exclude", "must_parent", "must_parent_all", "not_parent",
                "must_contain", "name_exact", "name_regex", "path_prefixes"]:
        if key in prof:
            prof[key] = parse_csv_list(prof[key])

    merged = dict(prof)
    merged.update({k: v for k, v in base_kwargs.items() if v not in [None, [], "", 0, False]})
    return merged

# ---------- Token & size budgeting ----------

def estimate_tokens_from_text(text: str) -> int:
    # rough heuristic. (~4 chars/token)
    return max(1, len(text) // 4)

def estimate_tokens_from_json(obj: Any) -> int:
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return estimate_tokens_from_text(s)

def trim_bundle_to_token_budget(bundle: Dict[str, Any], max_tokens: int) -> Dict[str, Any]:
    """
    Very simple budget trimmer: progressively trims arrays (top_files.snippets, head/tail)
    while staying under budget. Preserves ordering.
    """
    def size(o: Any) -> int:
        return estimate_tokens_from_json(o)

    if size(bundle) <= max_tokens:
        return bundle

    b = json.loads(json.dumps(bundle, ensure_ascii=False))  # deep-ish copy via JSON
    # trim top_files first
    tf = b.get("top_files") or []
    # Trim number of top files
    while tf and size(b) > max_tokens:
        tf.pop()  # drop last
    b["top_files"] = tf

    # If still large, trim each file’s snippets/head/tail
    for f in tf:
        if size(b) <= max_tokens:
            break
        for key in ["snippets", "peek_head", "peek_tail"]:
            arr = f.get(key)
            if isinstance(arr, list) and arr:
                # keep first half
                keep = max(0, len(arr) // 2)
                f[key] = arr[:keep]
                if size(b) <= max_tokens:
                    break

    # Final check; if still over, nuke trees
    if size(b) > max_tokens and "trees" in b:
        b["trees"] = {}
    return b

# ---------- Clustering helpers ----------

def common_prefix_components(paths: List[Path]) -> Dict[str, List[str]]:
    """
    Group by directory prefix (two levels) for a human-friendly cluster view.
    Returns {cluster_key: [str(path), ...]}
    """
    clusters: Dict[str, List[str]] = {}
    for p in paths:
        parts = list(p.resolve().parts)
        if len(parts) >= 2:
            key = str(Path(parts[-3] if len(parts) >= 3 else parts[-2]) / parts[-2])
        else:
            key = str(p.parent)
        clusters.setdefault(key, []).append(str(p))
    return clusters
