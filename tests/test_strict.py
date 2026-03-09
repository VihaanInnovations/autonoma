"""
Autonoma -- Strict Failure Gate

A security fixer gets less trust than a linter.
One bad rewrite poisons trust. This test is the gate.

HARD FAIL if ANY of these happen:
  1. Traceback on normal project input
  2. Syntax-breaking fix (compileall fails post-fix)
  3. Non-deterministic output (findings differ between runs)
  4. Duplicate rewrites on rerun (second fix changes files)
  5. Modifies files that should be ignored (already safe, test fixtures)
  6. Hangs or becomes absurdly slow
  7. Touches unsafe cases instead of refusing

Usage:
  python tests/test_strict.py
"""

import hashlib
import json
import os
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

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(target: str, args: List[str] = None) -> Tuple[int, str, float]:
    cmd = AUTONOMA + ["analyze", target] + (args or [])
    t0 = time.perf_counter()
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=TIMEOUT)
    return r.returncode, r.stdout, time.perf_counter() - t0


def hashes(d: Path) -> Dict[str, str]:
    h = {}
    for root, _, files in os.walk(d):
        for f in files:
            if f.endswith(".py"):
                fp = Path(root) / f
                h[str(fp.relative_to(d))] = hashlib.sha256(fp.read_bytes()).hexdigest()
    return h


def parse_json(text):
    depth = start = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try: return json.loads(text[start:i+1])
                except json.JSONDecodeError: continue
    return None


def parse_fix(text):
    depth = start = 0
    blocks = []
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0: blocks.append(text[start:i+1])
    for b in blocks:
        try:
            d = json.loads(b)
            if "fix_results" in d: return d
        except json.JSONDecodeError: continue
    return None


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class Gate:
    def __init__(self):
        self.checks: List[dict] = []
        self.failed = False

    def rule(self, name: str, ok: bool, detail: str = ""):
        entry = {"rule": name, "verdict": VERDICT_PASS if ok else VERDICT_FAIL}
        if detail:
            entry["detail"] = detail
        self.checks.append(entry)
        if not ok:
            self.failed = True
            print(f"  ** FAIL ** {name} -- {detail}")
        else:
            print(f"     PASS    {name}")

    def report(self):
        passed = sum(1 for c in self.checks if c["verdict"] == VERDICT_PASS)
        failed = sum(1 for c in self.checks if c["verdict"] == VERDICT_FAIL)
        return passed, failed


# ===========================================================================
# RULE 1: No traceback on normal input
# ===========================================================================

def rule_1_no_traceback(g: Gate, tmp: Path):
    print("\nRule 1: No traceback on normal project input")
    print("-" * 50)

    for name, gen in CATEGORY_A_GENERATORS.items():
        d = tmp / "r1" / name
        d.mkdir(parents=True)
        gen(d)
        code, out, _ = run(str(d))
        g.rule(f"[{name}] no traceback", "Traceback" not in out,
               out[out.index("Traceback"):out.index("Traceback")+200] if "Traceback" in out else "")

    # Also test with seeded benchmark
    bench = tmp / "r1" / "bench"
    bench.mkdir(parents=True)
    gen_seeded_benchmark(bench)
    code, out, _ = run(str(bench))
    g.rule("[benchmark] no traceback", "Traceback" not in out)

    # Ugly repo
    ugly = tmp / "r1" / "ugly"
    ugly.mkdir(parents=True)
    gen_ugly_repo(ugly)
    code, out, _ = run(str(ugly))
    g.rule("[ugly] no traceback", "Traceback" not in out)


# ===========================================================================
# RULE 2: No syntax-breaking fixes
# ===========================================================================

def rule_2_no_syntax_break(g: Gate, tmp: Path):
    print("\nRule 2: No syntax-breaking fix")
    print("-" * 50)

    # Seeded benchmark
    src = tmp / "r2" / "src"
    src.mkdir(parents=True)
    gen_seeded_benchmark(src)
    fix = tmp / "r2" / "fix"
    shutil.copytree(src, fix)

    run(str(fix), ["--auto-fix"])

    comp = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(fix)],
        capture_output=True, text=True, timeout=30,
    )
    g.rule("[benchmark] compileall post-fix", comp.returncode == 0,
           comp.stderr[:200] if comp.returncode != 0 else "")

    # AST parse every fixed file
    import ast
    for root, _, files in os.walk(fix):
        for f in files:
            if f.endswith(".py"):
                fp = Path(root) / f
                try:
                    ast.parse(fp.read_text(encoding="utf-8"))
                except SyntaxError as e:
                    g.rule(f"[{f}] valid syntax post-fix", False, str(e))

    # Synthetic 3k
    synth_src = tmp / "r2" / "synth_src"
    import random; random.seed(42)
    generate_repo(synth_src, 3000, inject_secrets=10, inject_safe=5, inject_unsupported=3)
    synth_fix = tmp / "r2" / "synth_fix"
    shutil.copytree(synth_src, synth_fix)
    run(str(synth_fix), ["--auto-fix"])

    comp2 = subprocess.run(
        [sys.executable, "-m", "compileall", "-q", str(synth_fix)],
        capture_output=True, text=True, timeout=30,
    )
    g.rule("[synth_3k] compileall post-fix", comp2.returncode == 0,
           comp2.stderr[:200] if comp2.returncode != 0 else "")


# ===========================================================================
# RULE 3: Deterministic output
# ===========================================================================

def rule_3_deterministic(g: Gate, tmp: Path):
    print("\nRule 3: Deterministic output")
    print("-" * 50)

    import random; random.seed(42)
    synth = tmp / "r3" / "synth"
    generate_repo(synth, 3000, inject_secrets=10, inject_safe=5, inject_unsupported=3)

    texts = []
    jsons = []
    for _ in range(3):
        _, out_t, _ = run(str(synth))
        texts.append(out_t)
        _, out_j, _ = run(str(synth), ["--format", "json"])
        d = parse_json(out_j)
        if d: d.pop("timestamp", None)
        jsons.append(json.dumps(d, sort_keys=True) if d else out_j)

    g.rule("text output identical x3", len(set(texts)) == 1,
           f"{len(set(texts))} distinct outputs")
    g.rule("json output identical x3", len(set(jsons)) == 1,
           f"{len(set(jsons))} distinct outputs")


# ===========================================================================
# RULE 4: No duplicate rewrites on rerun
# ===========================================================================

def rule_4_no_duplicate_rewrite(g: Gate, tmp: Path):
    print("\nRule 4: No duplicate rewrites on rerun")
    print("-" * 50)

    # Benchmark
    src = tmp / "r4" / "src"
    src.mkdir(parents=True)
    gen_seeded_benchmark(src)
    work = tmp / "r4" / "work"
    shutil.copytree(src, work)

    # First fix
    run(str(work), ["--auto-fix"])
    after_first = hashes(work)

    # Second fix
    _, out2, _ = run(str(work), ["--auto-fix", "--format", "json"])
    after_second = hashes(work)

    changes = {k for k in after_first if after_first.get(k) != after_second.get(k)}
    g.rule("[benchmark] zero changes on rerun", len(changes) == 0,
           f"changed: {changes}")

    # Check no duplicate imports
    for root, _, files in os.walk(work):
        for f in files:
            if f.endswith(".py"):
                fp = Path(root) / f
                content = fp.read_text(encoding="utf-8")
                top_imports = [l for l in content.split("\n")
                               if l.strip() == "import os"]
                if len(top_imports) > 1:
                    g.rule(f"[{f}] no duplicate 'import os'", False,
                           f"{len(top_imports)} occurrences")

    # Check no duplicate os.getenv
    for root, _, files in os.walk(work):
        for f in files:
            if f.endswith(".py"):
                fp = Path(root) / f
                lines = fp.read_text(encoding="utf-8").split("\n")
                getenv_lines = [l.strip() for l in lines if "os.getenv" in l]
                seen = set()
                for gl in getenv_lines:
                    if gl in seen:
                        g.rule(f"[{f}] no duplicate os.getenv", False, f"dup: {gl}")
                    seen.add(gl)

    # Synth
    import random; random.seed(42)
    synth = tmp / "r4" / "synth"
    generate_repo(synth, 3000, inject_secrets=10, inject_safe=5, inject_unsupported=3)
    synth_w = tmp / "r4" / "synth_w"
    shutil.copytree(synth, synth_w)

    run(str(synth_w), ["--auto-fix"])
    h1 = hashes(synth_w)
    run(str(synth_w), ["--auto-fix"])
    h2 = hashes(synth_w)

    ch = {k for k in h1 if h1.get(k) != h2.get(k)}
    g.rule("[synth_3k] zero changes on rerun", len(ch) == 0, f"changed: {ch}")


# ===========================================================================
# RULE 5: Does not modify ignored files
# ===========================================================================

def rule_5_no_ignored_mutation(g: Gate, tmp: Path):
    print("\nRule 5: Does not modify files that should be ignored")
    print("-" * 50)

    src = tmp / "r5" / "src"
    src.mkdir(parents=True)
    gen_seeded_benchmark(src)

    fix = tmp / "r5" / "fix"
    shutil.copytree(src, fix)

    pre = hashes(fix)
    run(str(fix), ["--auto-fix"])
    post = hashes(fix)

    # already_safe.py must NOT change
    if "already_safe.py" in pre:
        g.rule("already_safe.py unchanged",
               pre.get("already_safe.py") == post.get("already_safe.py"))

    # Dry-run must not change any file
    dry_dir = tmp / "r5" / "dry"
    shutil.copytree(src, dry_dir)
    pre_dry = hashes(dry_dir)
    run(str(dry_dir), ["--dry-run"])
    post_dry = hashes(dry_dir)
    g.rule("dry-run modifies zero files", pre_dry == post_dry,
           f"modified: {set(k for k in pre_dry if pre_dry.get(k) != post_dry.get(k))}")


# ===========================================================================
# RULE 6: No hang / absurd slowness
# ===========================================================================

def rule_6_no_hang(g: Gate, tmp: Path):
    print("\nRule 6: No hang / absurd slowness")
    print("-" * 50)

    import random; random.seed(42)

    # 3k LOC < 5s
    r3k = tmp / "r6" / "r3k"
    generate_repo(r3k, 3000, inject_secrets=10, inject_safe=5, inject_unsupported=3)
    _, _, t3 = run(str(r3k))
    g.rule("3k LOC < 5s", t3 < 5.0, f"{t3:.2f}s")

    # 10k LOC < 20s
    r10k = tmp / "r6" / "r10k"
    generate_repo(r10k, 10000, inject_secrets=20, inject_safe=5, inject_unsupported=3)
    _, _, t10 = run(str(r10k))
    g.rule("10k LOC < 20s", t10 < 20.0, f"{t10:.2f}s")

    # 30k LOC < 60s
    r30k = tmp / "r6" / "r30k"
    generate_repo(r30k, 30000, inject_secrets=40, inject_safe=5, inject_unsupported=3)
    _, _, t30 = run(str(r30k))
    g.rule("30k LOC < 60s", t30 < 60.0, f"{t30:.2f}s")

    # Ugly repo with 200 files < 120s
    ugly = tmp / "r6" / "ugly"
    ugly.mkdir(parents=True)
    gen_ugly_repo(ugly)
    _, _, tu = run(str(ugly))
    g.rule("ugly repo < 120s", tu < 120.0, f"{tu:.2f}s")


# ===========================================================================
# RULE 7: Does not touch unsafe cases
# ===========================================================================

def rule_7_no_unsafe_touch(g: Gate, tmp: Path):
    print("\nRule 7: Does not touch unsafe cases (refuses instead)")
    print("-" * 50)

    repo = tmp / "r7" / "repo"
    repo.mkdir(parents=True)

    # .env.example for env contract
    write_file(repo, ".env.example", "API_KEY=\nDB_PASSWORD=\nSECRET_TOKEN=\n")

    # Fixable: obvious hardcoded secrets (SHOULD be FIXED)
    write_file(repo, "fixable_secrets.py",
               '"""Has obvious secrets."""\nimport os\n\n'
               'db_password = "SuperSecret123!"\n'
               'api_key = "sk-live-abc123xyz789def456"\n'
               'secret_token = "ghp_1234567890abcdef1234567890abcdef12345678"\n')

    # Safe: already using getenv (must NOT be touched)
    write_file(repo, "already_safe.py",
               '"""Already safe."""\nimport os\n\n'
               'api_key = os.getenv("API_KEY", "")\n'
               'db_password = os.getenv("DB_PASSWORD")\n')

    fix_dir = tmp / "r7" / "fix"
    shutil.copytree(repo, fix_dir)
    pre = hashes(fix_dir)

    _, out, _ = run(str(fix_dir), ["--auto-fix", "--format", "json"])
    post = hashes(fix_dir)

    # already_safe.py must NOT change
    g.rule("already_safe.py untouched",
           pre.get("already_safe.py") == post.get("already_safe.py"))

    # fixable_secrets.py SHOULD change (proves fixer works)
    g.rule("fixable_secrets.py was fixed",
           pre.get("fixable_secrets.py") != post.get("fixable_secrets.py"),
           "file was not modified")

    # Parse fix results
    fd = parse_fix(out)
    if fd:
        results = fd["fix_results"]

        # REFUSED/SKIPPED must have reasons
        for fr in results:
            state = fr.get("state", "")
            if state in ("REFUSED", "SKIPPED"):
                g.rule(f"{state} has reason: {fr.get('issue_id','?')}",
                       bool(fr.get("reason")), f"missing reason for {state}")
            # FIXED must not be on already_safe
            if state == "FIXED":
                fname = Path(fr.get("file", "")).name
                g.rule("FIXED not on already_safe",
                       "already_safe" not in fname, f"wrongly fixed {fname}")

        # Must have at least one FIXED
        fixed_n = sum(1 for fr in results if fr["state"] == "FIXED")
        g.rule(f"Has FIXED outcomes ({fixed_n})", fixed_n > 0)
    else:
        # No fix_results = OK only if 0 findings
        scan = parse_json(out)
        total = scan.get("summary", {}).get("total_issues", -1) if scan else -1
        g.rule("No fix_results (0 findings = OK)",
               total == 0, f"had {total} findings but no fix_results")


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 60)
    print("AUTONOMA STRICT FAILURE GATE")
    print("A security fixer gets less trust than a linter.")
    print("=" * 60)

    g = Gate()

    with tempfile.TemporaryDirectory(prefix="autonoma_gate_") as tmp:
        t = Path(tmp)
        rule_1_no_traceback(g, t)
        rule_2_no_syntax_break(g, t)
        rule_3_deterministic(g, t)
        rule_4_no_duplicate_rewrite(g, t)
        rule_5_no_ignored_mutation(g, t)
        rule_6_no_hang(g, t)
        rule_7_no_unsafe_touch(g, t)

    passed, failed = g.report()
    print(f"\n{'='*60}")
    print(f"GATE RESULT: {passed} passed, {failed} failed")
    if failed == 0:
        print("VERDICT: PASS -- ship it")
    else:
        print("VERDICT: FAIL -- do not ship")
    print(f"{'='*60}")

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
