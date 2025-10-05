#!/usr/bin/env python3
"""
Example: Basic test suite for focus_probe
"""
import os
import subprocess
import json
import sys
from pathlib import Path

def run_probe(keyword, pattern, base, profile=None):
    """Run focus_probe and return parsed JSON"""
    script_path = str((Path(__file__).resolve().parents[1] / "focus_probe.py").resolve())
    cmd = [
        sys.executable, script_path,
        keyword, pattern,
        "-b", base,
        "--json",
        "--top-files", "5"
    ]
    if profile:
        cmd.extend(["--profile", profile])
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}")
        return None
    return json.loads(result.stdout)

def test_basic_search():
    """Test basic directory discovery + grep"""
    base = os.environ.get("FOCUS_TEST_BASE", "./bdai-main")
    bundle = run_probe("spot", "teleop", base)
    
    assert bundle is not None, "Probe failed"
    assert bundle["dirs_found"] > 0, "No directories found"
    assert bundle["files_with_hits"] > 0, "No files matched"
    print("✓ Basic search works")

def test_profile_usage():
    """Test profile-based search"""
    base = os.environ.get("FOCUS_TEST_BASE", "./bdai-main")
    bundle = run_probe("spot", "teleop", base, profile="teleop-scout")
    
    assert bundle is not None, "Probe with profile failed"
    assert bundle["profile"] == "teleop-scout", "Profile not applied"
    print("✓ Profile usage works")

def test_token_budgeting():
    """Test that results fit within token budget"""
    # Note: focus_probe doesn't have --budget-tokens in this version
    # This is a placeholder for when it's implemented
    base = os.environ.get("FOCUS_TEST_BASE", "./bdai-main")
    bundle = run_probe("spot", "teleop", base)
    
    if bundle and "token_estimate" in bundle:
        assert bundle["token_estimate"] < 50000, "Token estimate too high"
        print(f"✓ Token estimate: {bundle['token_estimate']}")

if __name__ == "__main__":
    print("Running Focus Tools Tests...\n")
    
    try:
        test_basic_search()
        test_profile_usage()
        test_token_budgeting()
        print("\n✓ All tests passed!")
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        sys.exit(1)
