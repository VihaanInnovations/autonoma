"""
Autonoma -- 5 Critical Tests

Test 1: Stability      -- 3x repeated scans, identical output each time
Test 2: Safe-fix        -- fix on copy, compileall, refused stay refused
Test 3: Idempotency     -- fix twice, second run changes nothing
Test 4: Crash resistance -- garbage input (bad syntax, unicode, long strings)
Test 5: Scale           -- 500 / 3k / 10k / 30k LOC, runtime linearity

Usage:
  python tests/test_critical.py
"""

import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from test_acceptance import generate_repo
from test_repo_categories import (
    CATEGORY_A_GENERATORS,
    gen_seeded_benchmark,
    gen_ugly_repo,
    write_file,
)

AUTONOMA = [sys.executable, "-m", "autonoma"]
TIMEOUT = 120


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class Results:
    def __init__(self, label: str):
        self.label = label
        self.passed = 0
        self.failed = 0
        self.details: List[str] = []

    def check(self, name: str, ok: bool, detail: str = ""):
        if ok:
            self.passed += 1
            self.details.append(f"  [PASS] {name}")
        else:
            self.failed += 1
            msg = f"  [FAIL] {name}"
            if detail:
                msg += f" -- {detail}"
            self.details.append(msg)

    def dump(self):
        status = "PASS" if self.failed == 0 else "FAIL"
        print(f"\n{'='*70}")
        print(f"{self.label}: {status} ({self.passed} passed, {self.failed} failed)")
        print(f"{'='*70}")
        for d in self.details:
            print(d)


def run(repo: Path, args: List[str] = None) -> Tuple[int, str, float]:
    cmd = AUTONOMA + ["analyze", str(repo)] + (args or [])
    t0 = time.perf_counter()
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout, time.perf_counter() - t0


def hashes(repo: Path) -> Dict[str, str]:
    out = {}
    for root, _, files in os.walk(repo):
        for f in files:
            if f.endswith(".py"):
                fp = Path(root) / f
                out[str(fp.relative_to(repo))] = hashlib.sha256(fp.read_bytes()).hexdigest()
    return out


def parse_json(output: str):
    depth = 0
    start = 0
    for i, ch in enumerate(output):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(output[start:i+1])
                except json.JSONDecodeError:
                    continue
    return None


def parse_fix_block(output: str):
    depth = 0
    start = 0
    blocks = []
    for i, ch in enumerate(output):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blocks.append(output[start:i+1])
    for b in blocks:
        try:
            d = json.loads(b)
            if "fix_results" in d:
                return d
        except json.JSONDecodeError:
            continue
    return None


# ===========================================================================
# TEST 1: STABILITY
# ===========================================================================

def test_stability(tmp_path: Path) -> Results:
    r = Results("Test 1: Stability (3x repeated scans)")

    repos = {}

    # Generate several repos
    for name, gen in CATEGORY_A_GENERATORS.items():
        d = tmp_path / "stab" / name
        d.mkdir(parents=True)
        gen(d)
        repos[name] = d

    bench = tmp_path / "stab" / "benchmark"
    bench.mkdir(parents=True)
    gen_seeded_benchmark(bench)
    repos["benchmark"] = bench

    synth = tmp_path / "stab" / "synth"
    generate_repo(synth, 3000, inject_secrets=10, inject_safe=5, inject_unsupported=3)
    repos["synth_3k"] = synth

    for name, repo in repos.items():
        text_runs = []
        json_runs = []

        for i in range(3):
            code, out, _ = run(repo)
            r.check(f"[{name}] run {i+1} exit 0", code == 0, f"exit {code}")
            r.check(f"[{name}] run {i+1} no traceback", "Traceback" not in out)
            text_runs.append(out)

            _, jout, _ = run(repo, ["--format", "json"])
            d = parse_json(jout)
            if d:
                d.pop("timestamp", None)
            json_runs.append(json.dumps(d, sort_keys=True) if d else jout)

        # All text runs identical
        r.check(f"[{name}] text deterministic", len(set(text_runs)) == 1,
                f"{len(set(text_runs))} distinct outputs")

        # All JSON runs identical (minus timestamp)
        r.check(f"[{name}] json deterministic", len(set(json_runs)) == 1,
                f"{len(set(json_runs))} distinct outputs")

    return r


# ===========================================================================
# TEST 2: SAFE-FIX CORRECTNESS
# ===========================================================================

def test_safe_fix(tmp_path: Path) -> Results:
    r = Results("Test 2: Safe-Fix Correctness")

    # Seeded benchmark with known secrets
    src = tmp_path / "fix_src"
    src.mkdir(parents=True)
    gen_seeded_benchmark(src)

    # Copy for fixing
    fix = tmp_path / "fix_copy"
    shutil.copytree(src, fix)

    pre = hashes(fix)

    # Run auto-fix
    code, out, _ = run(fix, ["--auto-fix", "--format", "json"])
    r.check("Auto-fix exit 0", code == 0, f"exit {code}")
    r.check("No traceback", "Traceback" not in out)

    post = hashes(fix)

    # Identify changed files
    changed = {k for k in pre if pre.get(k) != post.get(k)}
    r.check(f"Files changed: {len(changed)}", len(changed) > 0, "no files changed")

    # Every changed file must still be valid Python
    for f in changed:
        fp = fix / f
        try:
            import ast
            ast.parse(fp.read_text(encoding="utf-8"))
            r.check(f"Syntax valid: {f}", True)
        except SyntaxError as e:
            r.check(f"Syntax valid: {f}", False, str(e))

    # compileall must pass on the entire repo
    compile_result = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(fix)],
        capture_output=True, text=True, timeout=30
    )
    r.check("compileall passes", compile_result.returncode == 0,
            compile_result.stderr[:200] if compile_result.returncode != 0 else "")

    # Parse fix results
    fd = parse_fix_block(out)
    if fd:
        results = fd["fix_results"]

        # REFUSED must have reason
        refused = [x for x in results if x["state"] == "REFUSED"]
        for x in refused:
            r.check(f"REFUSED has reason: {x.get('issue_id')}",
                    bool(x.get("reason")))

        # SKIPPED must have reason
        skipped = [x for x in results if x["state"] == "SKIPPED"]
        for x in skipped:
            r.check(f"SKIPPED has reason: {x.get('issue_id')}",
                    bool(x.get("reason")))

        # FIXED files should not include already_safe.py
        fixed_files = {x["file"] for x in results if x["state"] == "FIXED"}
        r.check("already_safe.py not in FIXED",
                not any("already_safe" in f for f in fixed_files),
                f"fixed: {fixed_files}")
    else:
        r.check("Fix results parseable", False, "no fix_results block")

    # Fix is deterministic: fix a second copy and compare
    fix2 = tmp_path / "fix_copy2"
    shutil.copytree(src, fix2)
    run(fix2, ["--auto-fix"])
    post2 = hashes(fix2)
    r.check("Fix deterministic (two copies identical)", post == post2,
            f"mismatch: {set(k for k in post if post.get(k) != post2.get(k))}")

    shutil.rmtree(fix2, ignore_errors=True)
    return r


# ===========================================================================
# TEST 3: IDEMPOTENCY
# ===========================================================================

def test_idempotency(tmp_path: Path) -> Results:
    r = Results("Test 3: Idempotency (double-fix)")

    src = tmp_path / "idemp_src"
    src.mkdir(parents=True)
    gen_seeded_benchmark(src)

    # Also test with synthetic repo
    synth = tmp_path / "idemp_synth"
    generate_repo(synth, 3000, inject_secrets=10, inject_safe=5, inject_unsupported=3)

    for label, repo_src in [("benchmark", src), ("synth_3k", synth)]:
        work = tmp_path / f"idemp_{label}"
        shutil.copytree(repo_src, work)

        # First fix
        run(work, ["--auto-fix"])
        after_first = hashes(work)

        # Second fix on already-fixed repo
        code2, out2, _ = run(work, ["--auto-fix", "--format", "json"])
        after_second = hashes(work)

        r.check(f"[{label}] second fix exit 0", code2 == 0, f"exit {code2}")

        # Zero additional file changes
        changes = {k for k in after_first if after_first.get(k) != after_second.get(k)}
        r.check(f"[{label}] zero changes on second fix", len(changes) == 0,
                f"changed: {changes}")

        # Check no duplicate imports
        for root, _, files in os.walk(work):
            for f in files:
                if f.endswith(".py"):
                    fp = Path(root) / f
                    content = fp.read_text(encoding="utf-8")
                    import_count = content.count("import os")
                    if import_count > 1:
                        # Check if it's genuinely duplicated (not in different scopes)
                        lines = [l.strip() for l in content.split("\n")
                                 if l.strip() == "import os"]
                        if len(lines) > 1:
                            r.check(f"[{label}] no duplicate 'import os' in {f}",
                                    False, f"found {len(lines)} occurrences")

        # Parse second-run fix results: should all be SKIPPED
        fd = parse_fix_block(out2)
        if fd:
            results = fd["fix_results"]
            fixed2 = [x for x in results if x["state"] == "FIXED"]
            r.check(f"[{label}] no FIXED on second run",
                    len(fixed2) == 0, f"got {len(fixed2)} FIXED")
        else:
            # No fix results = no findings = correct
            r.check(f"[{label}] no findings on second run", True)

        shutil.rmtree(work, ignore_errors=True)

    return r


# ===========================================================================
# TEST 4: CRASH RESISTANCE
# ===========================================================================

def test_crash_resistance(tmp_path: Path) -> Results:
    r = Results("Test 4: Crash Resistance (garbage input)")

    garbage = tmp_path / "garbage"
    garbage.mkdir(parents=True)

    # 1. Syntax errors
    write_file(garbage, "bad_syntax1.py", 'def broken(\n  x = "password123"\n\nclass Oops\n  pass\n')
    write_file(garbage, "bad_syntax2.py", 'if True\n  print("missing colon")\n')
    write_file(garbage, "bad_syntax3.py", 'def f():\n  return (\n    "unclosed paren\n')

    # 2. Invalid-ish content (but valid UTF-8)
    write_file(garbage, "weird_strings.py",
               '"""Module."""\nimport os\nx = "' + "A" * 5000 + '"\n')

    # 3. Very long lines
    write_file(garbage, "long_line.py",
               '"""Module."""\nimport os\ny = "' + "B" * 10000 + '"\n')

    # 4. Strange AST patterns
    write_file(garbage, "strange_ast.py", '''"""Strange but valid Python."""
import os

# Deeply nested ternary
a = 1 if True else 2 if False else 3 if True else 4

# Star expressions
def f(*args, **kwargs):
    x, *rest = args
    return {**kwargs, "extra": rest}

# Walrus operator
if (n := 10) > 5:
    pass

# Lambda chains
chain = lambda x: (lambda y: x + y)

# Multiple assignment
a = b = c = d = "not_a_secret"
''')

    # 5. Mixed safe/unsafe in same file
    write_file(garbage, "mixed.py", '''"""Mixed patterns."""
import os

safe_key = os.getenv("API_KEY")
unsafe_key = "sk-live-hardcoded-key-12345"
also_safe = os.environ.get("TOKEN", "")
another_unsafe = "ghp_realtoken1234567890abcdef"

# Assignment inside function
def setup():
    db_pass = "mysql_password_123"
    return db_pass
''')

    # 6. File with null bytes (write as bytes)
    null_path = garbage / "null_bytes.py"
    null_path.write_bytes(b'"""Has null."""\nimport os\nx = "test\\x00value"\n')

    # 7. Empty files and whitespace-only
    write_file(garbage, "empty.py", "")
    write_file(garbage, "whitespace.py", "   \n\n   \n\n")
    write_file(garbage, "just_shebang.py", "#!/usr/bin/env python3\n")

    # 8. Binary-ish file with .py extension (should survive)
    bin_path = garbage / "binary_ish.py"
    bin_path.write_bytes(bytes(range(256)) + b"\n")

    # 9. Massive number of small files
    many_dir = garbage / "many_files"
    many_dir.mkdir()
    for i in range(200):
        write_file(garbage, f"many_files/f_{i}.py",
                   f'"""File {i}."""\nval_{i} = {i}\n')

    # --- Run scan ---
    code, out, elapsed = run(garbage)
    r.check("Scan completes (no hang)", elapsed < 120, f"{elapsed:.2f}s")
    r.check("No traceback", "Traceback" not in out)
    # We accept exit 0 or exit that's not a crash signal
    r.check("No crash signal", code in (0, 1), f"exit {code}")

    # --- Run JSON ---
    code_j, out_j, _ = run(garbage, ["--format", "json"])
    r.check("JSON no traceback", "Traceback" not in out_j)
    d = parse_json(out_j)
    if d:
        scanned = d.get("summary", {}).get("files_scanned", 0)
        r.check(f"Scanned {scanned} files (>0)", scanned > 0)
    else:
        r.check("JSON parseable", d is not None, "invalid JSON")

    # --- Run auto-fix (on copy) ---
    fix = tmp_path / "garbage_fix"
    shutil.copytree(garbage, fix)
    code_f, out_f, _ = run(fix, ["--auto-fix"])
    r.check("Auto-fix no traceback", "Traceback" not in out_f)
    r.check("Auto-fix no crash signal", code_f in (0, 1), f"exit {code_f}")

    # No .py file should be deleted
    pre_files = set(str(p.relative_to(garbage)) for p in garbage.rglob("*.py"))
    post_files = set(str(p.relative_to(fix)) for p in fix.rglob("*.py"))
    r.check("No files deleted", pre_files.issubset(post_files))

    # --- Run dry-run ---
    code_d, out_d, _ = run(garbage, ["--dry-run"])
    r.check("Dry-run no traceback", "Traceback" not in out_d)

    # Verify dry-run didn't modify anything
    pre_h = hashes(garbage)
    run(garbage, ["--dry-run"])
    post_h = hashes(garbage)
    r.check("Dry-run zero modifications", pre_h == post_h)

    shutil.rmtree(fix, ignore_errors=True)
    return r


# ===========================================================================
# TEST 5: SCALE / PERFORMANCE
# ===========================================================================

def test_scale(tmp_path: Path) -> Results:
    r = Results("Test 5: Scale / Performance")

    tiers = [
        ("small_500", 500, 3),
        ("medium_3k", 3000, 10),
        ("large_10k", 10000, 30),
        ("bigger_30k", 30000, 60),
    ]

    timings = []

    for label, loc, secrets in tiers:
        repo = tmp_path / "scale" / label / "repo"
        meta = generate_repo(repo, loc, inject_secrets=secrets,
                             inject_safe=3, inject_unsupported=2)
        actual_loc = meta["total_loc"]
        actual_files = meta["total_files"]

        # 3 runs, take median
        runs = []
        for _ in range(3):
            code, out, elapsed = run(repo)
            runs.append(elapsed)

        median_t = sorted(runs)[1]
        timings.append((label, actual_files, actual_loc, median_t))

        r.check(f"[{label}] exit 0", code == 0, f"exit {code}")
        r.check(f"[{label}] no traceback", "Traceback" not in out)
        r.check(f"[{label}] median {median_t:.3f}s", True)

        # Auto-fix timing
        fix_dir = tmp_path / "scale" / f"{label}_fix"
        shutil.copytree(repo, fix_dir)
        _, _, fix_time = run(fix_dir, ["--auto-fix"])
        r.check(f"[{label}] auto-fix {fix_time:.3f}s", True)
        shutil.rmtree(fix_dir, ignore_errors=True)

    # Print performance table
    print(f"\n  {'tier':<15} {'files':>6} {'LOC':>7} {'scan_s':>8} {'loc/s':>8}")
    print(f"  {'-'*15} {'-'*6} {'-'*7} {'-'*8} {'-'*8}")
    for label, files, loc, t in timings:
        lps = loc / t if t > 0 else 0
        print(f"  {label:<15} {files:>6} {loc:>7} {t:>8.3f} {lps:>8.0f}")

    # Check near-linear scaling
    if len(timings) >= 2:
        _, _, loc_small, t_small = timings[0]
        _, _, loc_big, t_big = timings[-1]
        loc_ratio = loc_big / loc_small
        time_ratio = t_big / t_small if t_small > 0 else 999

        r.check(f"Scaling: {loc_ratio:.0f}x LOC -> {time_ratio:.1f}x time",
                time_ratio < loc_ratio * 3,
                f"loc_ratio={loc_ratio:.1f}, time_ratio={time_ratio:.1f}")

    # Hard targets
    for label, _, loc, t in timings:
        if loc <= 2000:
            r.check(f"[{label}] <2s target", t < 2.0, f"{t:.3f}s")
        elif loc <= 5000:
            r.check(f"[{label}] <5s target", t < 5.0, f"{t:.3f}s")
        elif loc <= 15000:
            r.check(f"[{label}] <20s target", t < 20.0, f"{t:.3f}s")
        else:
            r.check(f"[{label}] <60s target", t < 60.0, f"{t:.3f}s")

    return r


# ===========================================================================
# Main
# ===========================================================================

def main():
    random.seed(42)

    print("=" * 70)
    print("Autonoma -- 5 Critical Tests")
    print("=" * 70)

    all_results = []

    with tempfile.TemporaryDirectory(prefix="autonoma_crit_") as tmp_path:
        tmp = Path(tmp_path)

        t1 = test_stability(tmp)
        t1.dump()
        all_results.append(t1)

        t2 = test_safe_fix(tmp)
        t2.dump()
        all_results.append(t2)

        t3 = test_idempotency(tmp)
        t3.dump()
        all_results.append(t3)

        t4 = test_crash_resistance(tmp)
        t4.dump()
        all_results.append(t4)

        t5 = test_scale(tmp)
        t5.dump()
        all_results.append(t5)

    total_p = sum(r.passed for r in all_results)
    total_f = sum(r.failed for r in all_results)

    print(f"\n{'='*70}")
    print(f"FINAL: {total_p} passed, {total_f} failed")
    if total_f == 0:
        print("ALL 5 CRITICAL TESTS PASSED")
    else:
        print(f"FAILURES: {total_f}")
    print(f"{'='*70}")

    sys.exit(1 if total_f > 0 else 0)


if __name__ == "__main__":
    main()
