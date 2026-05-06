#!/usr/bin/env python3
"""Grep unseen repos for secret-like assignments not caught by scanner."""
import json
import re
from pathlib import Path

REPOS = Path("bench/repos")
RAW = Path("bench/reports/sec002_validation/raw")
UNSEEN = ["sqlalchemy", "pydantic", "celery", "black", "mypy"]
SKIP_DIRS = {"tests", "test", "docs", "docs_src", ".git", "fixtures", "testdata"}

PATTERNS = [
    r'token\s*=\s*["\'][^"\']{8,}["\']',
    r'api_key\s*=\s*["\'][^"\']{8,}["\']',
    r'apiKey\s*=\s*["\'][^"\']{8,}["\']',
    r'secret\s*=\s*["\'][^"\']{8,}["\']',
    r'auth_token\s*=\s*["\'][^"\']{8,}["\']',
    r'github_token\s*=\s*["\'][^"\']{8,}["\']',
    r'bearer\s*=\s*["\'][^"\']{8,}["\']',
    r'password\s*=\s*["\'][^"\']{8,}["\']',
]

found_keys: set = set()
for repo in UNSEEN:
    p = RAW / f"{repo}.json"
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
        for f in data.get("findings", []):
            found_keys.add((repo, f["file"].replace("\\", "/"), f["line"]))

suspicious = []
for repo in UNSEEN:
    repo_path = REPOS / repo
    for pyfile in repo_path.rglob("*.py"):
        parts = set(pyfile.relative_to(repo_path).parts)
        if parts & SKIP_DIRS:
            continue
        try:
            text = pyfile.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for pat in PATTERNS:
            for m in re.finditer(pat, text, re.IGNORECASE):
                lineno = text[:m.start()].count("\n") + 1
                rel = str(pyfile.relative_to(repo_path)).replace("\\", "/")
                key = (repo, rel, lineno)
                if key in found_keys:
                    continue
                line = m.group(0).strip()
                # Skip obvious safe patterns
                if any(x in line for x in ["os.getenv", "os.environ", "process.env", "getenv("]):
                    continue
                suspicious.append({"repo": repo, "file": rel, "line": lineno, "match": line[:120]})

# Deduplicate
seen: set = set()
unique: list = []
for s in suspicious:
    k = (s["repo"], s["file"], s["line"])
    if k not in seen:
        seen.add(k)
        unique.append(s)

print(f"Suspicious non-flagged assignments in unseen repos: {len(unique)}")
for s in unique[:35]:
    print(f"  [{s['repo']}] {s['file']}:{s['line']}")
    print(f"    {s['match']}")
