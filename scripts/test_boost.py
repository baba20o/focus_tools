#!/usr/bin/env python3
"""Test the definition boost logic"""

from pathlib import Path
import re

def detect_definition_boost_debug(file_path: Path, pattern: str, has_h1: bool = False) -> float:
    """Debug version with print statements"""
    import re
    
    boost = 1.0
    reason = []
    
    keyword = pattern.lower()
    if '|' in pattern or '(' in pattern or '[' in pattern:
        match = re.search(r'\w{3,}', pattern)
        if match:
            keyword = match.group(0).lower()
    
    # README in matching directory
    if file_path.name.lower() == "readme.md":
        parts = [p.lower() for p in file_path.parts]
        if keyword in parts:
            try:
                kw_idx = parts.index(keyword)
                if len(parts) >= 2 and parts[-2] == keyword:
                    boost = 5.0
                    reason.append(f"README in /{keyword}/ directory")
                elif kw_idx >= 0 and kw_idx < len(parts) - 1:
                    boost = 3.0
                    reason.append(f"README under /{keyword}/ tree")
            except ValueError:
                pass
    
    # H1 header
    if has_h1:
        boost = max(boost, 2.5)
        if boost == 2.5:
            reason.append("Has H1 header")
    
    return boost, reason

# Test cases
test_files = [
    ("projects/amp/README.md", "AMP", True),  # Should be 5.0
    ("projects/amp/ws/src/alpha_orchestrator/README.md", "AMP", True),  # Should be 3.0
    ("projects/amp/docs/pages/Overview.md", "AMP", False),  # Should be 3.0
]

for path_str, pattern, has_h1 in test_files:
    p = Path(path_str)
    boost, reason = detect_definition_boost_debug(p, pattern, has_h1)
    print(f"{boost:4.1f}x | {path_str:60} | {', '.join(reason) if reason else 'no boost'}")
