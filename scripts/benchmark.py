#!/usr/bin/env python3
"""
benchmark.py - Run focus_llm against the AMP test questions and grade results.

Usage:
    python benchmark.py -b ./bdai-main [--trace-dir traces/]
"""
from __future__ import annotations
import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

# Load .env so OPENAI_* and other vars are available without shell piping
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass


def run_focus_llm(question: str, base: Path, trace_file: Path | None = None, llm_verbose: bool = False, llm_debug: bool = False) -> Tuple[str, float, bool]:
    """Run focus_llm and return (answer, latency_seconds, success)"""
    cmd = [
        sys.executable,
        str(Path(__file__).resolve().parents[1] / "focus_llm.py"),
        question,
        "-b",
        str(base),
    ]
    
    if trace_file:
        cmd.extend(["--trace-out", str(trace_file)])
    if llm_verbose:
        cmd.append("--verbose")
    if llm_debug:
        cmd.append("--debug-llm")
    
    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120  # 2 minute timeout per question
        )
        latency = time.time() - start
        
        if result.returncode != 0:
            print(f"  ❌ ERROR: {result.stderr[:200]}", file=sys.stderr)
            return f"[ERROR: {result.stderr[:100]}]", latency, False
        
        return result.stdout.strip(), latency, True
        
    except subprocess.TimeoutExpired:
        latency = time.time() - start
        return "[TIMEOUT: Exceeded 120s]", latency, False
    except Exception as e:
        latency = time.time() - start
        return f"[EXCEPTION: {str(e)}]", latency, False


def grade_answer(question: str, expected: str, actual: str) -> Tuple[int, str]:
    """
    Manual grading helper - prints comparison and waits for human grade (1-5).
    
    Returns: (grade, reasoning)
    """
    print("\n" + "="*80)
    print(f"QUESTION: {question}")
    print("-"*80)
    print(f"EXPECTED:\n{expected}")
    print("-"*80)
    print(f"ACTUAL:\n{actual}")
    print("="*80)
    
    while True:
        try:
            grade_input = input("Grade (1-5, or 's' to skip): ").strip().lower()
            if grade_input == 's':
                return 0, "skipped"
            grade = int(grade_input)
            if 1 <= grade <= 5:
                reasoning = input("Reasoning (optional): ").strip() or "n/a"
                return grade, reasoning
            print("Please enter 1-5")
        except ValueError:
            print("Please enter a number 1-5 or 's' to skip")
        except KeyboardInterrupt:
            print("\n\nBenchmark interrupted.")
            sys.exit(1)


def auto_grade(expected: str, actual: str) -> Tuple[int, str]:
    """
    Simple heuristic auto-grading:
    - 5: Contains all key terms from expected
    - 4: Contains most key terms
    - 3: Contains some key terms
    - 2: Vaguely related
    - 1: Wrong or error
    """
    if actual.startswith("[ERROR") or actual.startswith("[TIMEOUT") or actual.startswith("[EXCEPTION"):
        return 1, "system_error"
    
    # Extract key terms (simple word matching, case-insensitive)
    expected_lower = expected.lower()
    actual_lower = actual.lower()
    
    # Key term extraction (words longer than 3 chars, excluding common words)
    stop_words = {"the", "and", "for", "with", "that", "this", "from", "have", "will", "what", "when", "where"}
    expected_words = {w.strip(".,;:()[]{}\"'") for w in expected_lower.split() if len(w) > 3 and w not in stop_words}
    
    if not expected_words:
        return 3, "auto_no_key_terms"
    
    # Count how many key terms appear in actual
    matches = sum(1 for word in expected_words if word in actual_lower)
    coverage = matches / len(expected_words)
    
    if coverage >= 0.8:
        return 5, f"auto_high_coverage_{coverage:.2f}"
    elif coverage >= 0.6:
        return 4, f"auto_good_coverage_{coverage:.2f}"
    elif coverage >= 0.4:
        return 3, f"auto_some_coverage_{coverage:.2f}"
    elif coverage >= 0.2:
        return 2, f"auto_low_coverage_{coverage:.2f}"
    else:
        return 1, f"auto_minimal_coverage_{coverage:.2f}"


def main():
    parser = argparse.ArgumentParser(description="Benchmark focus_llm against AMP test questions")
    parser.add_argument("-b", "--base", required=True, help="Base repository path")
    parser.add_argument("--csv", default="AMP_Test_Questions.csv", help="CSV file with questions")
    parser.add_argument("--trace-dir", default=None, help="Directory to save trace files")
    parser.add_argument("--auto-grade", action="store_true", help="Use automatic grading (heuristic)")
    parser.add_argument("--output", default="benchmark_results.json", help="Output results JSON file")
    parser.add_argument("--llm-verbose", action="store_true", help="Pass --verbose to focus_llm for step logging")
    parser.add_argument("--llm-debug", action="store_true", help="Pass --debug-llm to focus_llm to show prompts and outputs")
    parser.add_argument("--start-from", type=int, default=0, help="Start from question N (0-indexed)")
    
    args = parser.parse_args()
    
    base = Path(args.base).expanduser().resolve()
    csv_path = Path(args.csv)
    
    if not base.exists():
        print(f"Error: Base path not found: {base}", file=sys.stderr)
        return 1
    
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1
    
    # Create trace directory if specified
    trace_dir = None
    if args.trace_dir:
        trace_dir = Path(args.trace_dir)
        trace_dir.mkdir(exist_ok=True)
    
    # Load questions
    questions: List[Dict[str, str]] = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        questions = list(reader)
    
    print(f"Loaded {len(questions)} questions from {csv_path}")
    print(f"Base repository: {base}")
    print(f"Auto-grading: {args.auto_grade}")
    print()
    
    # Run benchmark
    results = []
    total_latency = 0.0
    
    for i, row in enumerate(questions):
        if i < args.start_from:
            continue
            
        question = row['question']
        expected = row['expected_answer']
        
        print(f"\n[{i+1}/{len(questions)}] Running: {question[:60]}...")
        
        trace_file = None
        if trace_dir:
            trace_file = trace_dir / f"trace_{i:02d}.json"
        
        actual, latency, success = run_focus_llm(question, base, trace_file, args.llm_verbose, args.llm_debug)
        total_latency += latency
        
        print(f"  ⏱️  Latency: {latency:.2f}s")
        
        # Grade
        if args.auto_grade:
            grade, reasoning = auto_grade(expected, actual)
            print(f"  🎯 Auto-grade: {grade}/5 ({reasoning})")
        else:
            grade, reasoning = grade_answer(question, expected, actual)
        
        result = {
            "question_num": i + 1,
            "question": question,
            "expected": expected,
            "actual": actual,
            "grade": grade,
            "reasoning": reasoning,
            "latency_seconds": round(latency, 2),
            "success": success,
            "trace_file": str(trace_file) if trace_file else None,
        }
        results.append(result)
        
        # Save intermediate results
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump({
                "total_questions": len(questions),
                "completed": len(results),
                "results": results,
            }, f, indent=2, ensure_ascii=False)
        
        print(f"  ✅ Grade: {grade}/5")
    
    # Final summary
    print("\n" + "="*80)
    print("BENCHMARK COMPLETE")
    print("="*80)
    
    graded = [r for r in results if r['grade'] > 0]
    if graded:
        avg_grade = sum(r['grade'] for r in graded) / len(graded)
        avg_latency = total_latency / len(results)
        
        print(f"Questions answered: {len(results)}/{len(questions)}")
        print(f"Average grade: {avg_grade:.2f}/5.00")
        print(f"Average latency: {avg_latency:.2f}s")
        print(f"Total time: {total_latency:.1f}s")
        
        # Grade distribution
        print("\nGrade distribution:")
        for g in range(1, 6):
            count = sum(1 for r in results if r['grade'] == g)
            bar = "█" * count
            print(f"  {g}/5: {bar} ({count})")
        
        # Success rate
        success_count = sum(1 for r in results if r['success'])
        print(f"\nSuccess rate: {success_count}/{len(results)} ({success_count/len(results)*100:.1f}%)")
    
    print(f"\nResults saved to: {args.output}")
    if trace_dir:
        print(f"Traces saved to: {trace_dir}/")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
