"""
Autonoma -- Three-Category Repo Test Suite

Category A: Clean real-shaped Python repos
  - CLI tool, Flask app, Django app, library, data project
  - Tests: parser stability, traversal, false positives, performance

Category B: Seeded benchmark repos
  - Known secrets, safe patterns, refusal cases
  - Tests: detection accuracy, fix correctness, refusal semantics

Category C: Ugly/adversarial repos
  - Syntax errors, weird encodings, nested dirs, huge files
  - Tests: resilience, graceful degradation, no crashes

Usage:
  python tests/test_repo_categories.py
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

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

AUTONOMA_CMD = [sys.executable, "-m", "autonoma"]
TIMEOUT_SECONDS = 120


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

class TestResults:
    def __init__(self, label: str):
        self.label = label
        self.passed = 0
        self.failed = 0
        self.details = []

    def check(self, name: str, condition: bool, detail: str = ""):
        if condition:
            self.passed += 1
            self.details.append(f"  [PASS] {name}")
        else:
            self.failed += 1
            msg = f"  [FAIL] {name}"
            if detail:
                msg += f" -- {detail}"
            self.details.append(msg)

    def summary(self) -> str:
        status = "PASS" if self.failed == 0 else "FAIL"
        header = (f"\n{'='*60}\n"
                  f"{self.label}: {status} ({self.passed} passed, {self.failed} failed)\n"
                  f"{'='*60}")
        return header + "\n" + "\n".join(self.details)


def run_autonoma(repo_dir: Path, args: List[str] = None) -> Tuple[int, str, float]:
    """Run autonoma and return (exit_code, combined_output, elapsed_seconds)."""
    cmd = AUTONOMA_CMD + ["analyze", str(repo_dir)] + (args or [])
    start = time.perf_counter()
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    elapsed = time.perf_counter() - start
    return result.returncode, result.stdout, elapsed


def compute_file_hashes(repo_dir: Path) -> Dict[str, str]:
    hashes = {}
    for root, _, filenames in os.walk(repo_dir):
        for fname in filenames:
            if fname.endswith(".py"):
                fpath = Path(root) / fname
                hashes[str(fpath.relative_to(repo_dir))] = (
                    hashlib.sha256(fpath.read_bytes()).hexdigest()
                )
    return hashes


def write_file(base: Path, relpath: str, content: str):
    fp = base / relpath
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content, encoding="utf-8")


# ===========================================================================
# CATEGORY A: Clean Real-Shaped Repos
# ===========================================================================

def gen_cli_tool(base: Path):
    """Realistic CLI tool structure (like click/typer project)."""
    write_file(base, "__init__.py", '"""CLI tool package."""\n__version__ = "1.0.0"\n')
    write_file(base, "cli.py", '''"""CLI entry point."""
import click
import os
import sys
import json
from pathlib import Path


@click.group()
@click.version_option()
def main():
    """A sample CLI tool."""
    pass


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--output", "-o", default="-", help="Output file")
@click.option("--verbose", "-v", is_flag=True)
def process(path, output, verbose):
    """Process files in the given path."""
    results = []
    for root, dirs, files in os.walk(path):
        for f in files:
            fpath = Path(root) / f
            if verbose:
                click.echo(f"Processing: {fpath}")
            results.append({"file": str(fpath), "size": fpath.stat().st_size})

    payload = json.dumps(results, indent=2)
    if output == "-":
        click.echo(payload)
    else:
        Path(output).write_text(payload)
        click.echo(f"Written to {output}")


@main.command()
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="text")
def status(fmt):
    """Show system status."""
    info = {
        "python": sys.version,
        "platform": sys.platform,
        "cwd": os.getcwd(),
    }
    if fmt == "json":
        click.echo(json.dumps(info, indent=2))
    else:
        for k, v in info.items():
            click.echo(f"{k}: {v}")
''')
    write_file(base, "utils.py", '''"""Utility functions."""
import hashlib
import re
from typing import Optional, List


def hash_file(path: str) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def paginate(items: List, page: int = 1, per_page: int = 25) -> dict:
    """Simple pagination helper."""
    start = (page - 1) * per_page
    end = start + per_page
    return {
        "items": items[start:end],
        "total": len(items),
        "page": page,
        "per_page": per_page,
        "pages": (len(items) + per_page - 1) // per_page,
    }


def validate_email(email: str) -> bool:
    """Basic email validation."""
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))
''')
    write_file(base, "config.py", '''"""Configuration management."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    debug: bool = False
    log_level: str = "INFO"
    output_dir: str = "./output"
    max_workers: int = 4

    @classmethod
    def from_env(cls):
        return cls(
            debug=os.getenv("DEBUG", "false").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            output_dir=os.getenv("OUTPUT_DIR", "./output"),
            max_workers=int(os.getenv("MAX_WORKERS", "4")),
        )
''')


def gen_flask_app(base: Path):
    """Realistic Flask app structure."""
    write_file(base, "__init__.py", '"""Flask application."""\n')
    write_file(base, "app.py", '''"""Flask application factory."""
import os
from flask import Flask, jsonify, request


def create_app(config_name=None):
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "false").lower() == "true"

    @app.route("/health")
    def health():
        return jsonify({"status": "ok"})

    @app.route("/api/items", methods=["GET"])
    def list_items():
        page = request.args.get("page", 1, type=int)
        return jsonify({"items": [], "page": page})

    @app.route("/api/items", methods=["POST"])
    def create_item():
        data = request.get_json()
        if not data or "name" not in data:
            return jsonify({"error": "name required"}), 400
        return jsonify({"id": 1, "name": data["name"]}), 201

    return app
''')
    write_file(base, "models.py", '''"""Database models."""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class User:
    id: int
    username: str
    email: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_active: bool = True

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
            "is_active": self.is_active,
        }


@dataclass
class Item:
    id: int
    name: str
    description: Optional[str] = None
    owner_id: Optional[int] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "owner_id": self.owner_id,
            "tags": self.tags,
        }
''')
    write_file(base, "auth.py", '''"""Authentication helpers."""
import os
import hashlib
import hmac
import secrets
from functools import wraps


def generate_token(length: int = 32) -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(length)


def hash_password(password: str, salt: str = None) -> tuple:
    """Hash a password with optional salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return hashed.hex(), salt


def verify_password(password: str, hashed: str, salt: str) -> bool:
    """Verify a password against its hash."""
    computed, _ = hash_password(password, salt)
    return hmac.compare_digest(computed, hashed)


def require_auth(f):
    """Decorator for routes requiring authentication."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = None
        auth_header = os.getenv("AUTH_HEADER", "Authorization")
        # This is just a skeleton
        if not token:
            return {"error": "unauthorized"}, 401
        return f(*args, **kwargs)
    return wrapper
''')


def gen_django_app(base: Path):
    """Realistic Django project structure."""
    write_file(base, "__init__.py", '"""Django project."""\n')
    write_file(base, "settings.py", '''"""Django settings."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-dev-key-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() == "true"
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]

ROOT_URLCONF = "myproject.urls"

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.sqlite3"),
        "NAME": os.getenv("DB_NAME", str(BASE_DIR / "db.sqlite3")),
        "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", ""),
        "PORT": os.getenv("DB_PORT", ""),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
''')
    write_file(base, "views.py", '''"""Django views."""
import json
from typing import Any


class JsonResponse:
    """Minimal JSON response stub."""
    def __init__(self, data: Any, status: int = 200):
        self.data = data
        self.status = status
        self.content = json.dumps(data)


def index(request):
    return JsonResponse({"message": "Welcome"})


def user_list(request):
    users = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    return JsonResponse({"users": users})


def user_detail(request, user_id: int):
    return JsonResponse({"id": user_id, "name": "User"})
''')
    write_file(base, "urls.py", '''"""URL configuration."""

urlpatterns = [
    # path("", views.index, name="index"),
    # path("users/", views.user_list, name="user_list"),
]
''')
    write_file(base, "management/__init__.py", '"""Management commands."""\n')
    write_file(base, "management/commands/__init__.py", '"""Custom commands."""\n')
    write_file(base, "management/commands/seed_db.py", '''"""Seed database command."""
import random
import string


def random_string(length: int = 10) -> str:
    return "".join(random.choices(string.ascii_letters, k=length))


def seed_users(count: int = 10):
    """Generate seed users."""
    users = []
    for i in range(count):
        users.append({
            "username": f"user_{random_string(6)}",
            "email": f"user{i}@example.com",
        })
    return users


def seed_items(count: int = 50):
    """Generate seed items."""
    items = []
    for i in range(count):
        items.append({
            "name": f"Item {random_string(8)}",
            "description": f"Description for item {i}",
        })
    return items


if __name__ == "__main__":
    print(f"Created {len(seed_users())} users")
    print(f"Created {len(seed_items())} items")
''')


def gen_library_package(base: Path):
    """Realistic library/package structure."""
    write_file(base, "__init__.py", '''"""A utility library."""
__version__ = "2.3.1"

from .core import transform, validate
from .formatters import format_output
''')
    write_file(base, "core.py", '''"""Core transformation and validation logic."""
import re
from typing import Any, Dict, List, Optional, Union


def transform(data: Dict[str, Any], rules: List[dict] = None) -> Dict[str, Any]:
    """Apply transformation rules to data."""
    if rules is None:
        rules = []

    result = dict(data)
    for rule in rules:
        field = rule.get("field")
        action = rule.get("action", "identity")

        if field not in result:
            continue

        if action == "uppercase":
            result[field] = str(result[field]).upper()
        elif action == "lowercase":
            result[field] = str(result[field]).lower()
        elif action == "strip":
            result[field] = str(result[field]).strip()
        elif action == "remove":
            del result[field]

    return result


def validate(data: Dict[str, Any], schema: Dict[str, str]) -> List[str]:
    """Validate data against a simple schema. Returns list of errors."""
    errors = []
    for field, field_type in schema.items():
        if field not in data:
            errors.append(f"Missing required field: {field}")
            continue

        value = data[field]
        if field_type == "string" and not isinstance(value, str):
            errors.append(f"{field}: expected string, got {type(value).__name__}")
        elif field_type == "int" and not isinstance(value, int):
            errors.append(f"{field}: expected int, got {type(value).__name__}")
        elif field_type == "float" and not isinstance(value, (int, float)):
            errors.append(f"{field}: expected float, got {type(value).__name__}")
        elif field_type == "list" and not isinstance(value, list):
            errors.append(f"{field}: expected list, got {type(value).__name__}")
        elif field_type == "email":
            if not re.match(r"^[^@]+@[^@]+\\.[^@]+$", str(value)):
                errors.append(f"{field}: invalid email format")

    return errors


def merge_dicts(*dicts: Dict) -> Dict:
    """Deep merge multiple dictionaries."""
    result = {}
    for d in dicts:
        for key, value in d.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = merge_dicts(result[key], value)
            else:
                result[key] = value
    return result
''')
    write_file(base, "formatters.py", '''"""Output formatters."""
import json
import csv
import io
from typing import Any, List, Dict


def format_output(data: Any, fmt: str = "json") -> str:
    """Format data in the requested format."""
    if fmt == "json":
        return json.dumps(data, indent=2, default=str)
    elif fmt == "csv":
        return _to_csv(data)
    elif fmt == "text":
        return _to_text(data)
    else:
        raise ValueError(f"Unknown format: {fmt}")


def _to_csv(data: Any) -> str:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        return output.getvalue()
    return str(data)


def _to_text(data: Any) -> str:
    if isinstance(data, dict):
        lines = [f"{k}: {v}" for k, v in data.items()]
        return "\\n".join(lines)
    elif isinstance(data, list):
        return "\\n".join(str(item) for item in data)
    return str(data)
''')
    write_file(base, "exceptions.py", '''"""Custom exceptions."""


class ValidationError(Exception):
    """Raised when data validation fails."""
    def __init__(self, errors: list):
        self.errors = errors
        super().__init__(f"Validation failed: {', '.join(errors)}")


class TransformError(Exception):
    """Raised when a transformation fails."""
    pass


class ConfigError(Exception):
    """Raised for configuration issues."""
    pass
''')


def gen_data_project(base: Path):
    """Realistic data/ML project structure."""
    write_file(base, "__init__.py", '"""Data processing project."""\n')
    write_file(base, "pipeline.py", '''"""Data pipeline."""
import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class Pipeline:
    """Simple ETL pipeline."""

    def __init__(self, source_dir: str, output_dir: str):
        self.source_dir = Path(source_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.steps = []

    def add_step(self, name: str, func):
        self.steps.append({"name": name, "func": func})
        return self

    def run(self, data: List[Dict]) -> List[Dict]:
        logger.info(f"Running pipeline with {len(self.steps)} steps on {len(data)} records")
        result = data
        for step in self.steps:
            logger.info(f"  Step: {step['name']}")
            result = step["func"](result)
            logger.info(f"    Output: {len(result)} records")
        return result

    def save_results(self, data: List[Dict], filename: str = "output.json"):
        output_path = self.output_dir / filename
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Saved {len(data)} records to {output_path}")


def filter_nulls(records: List[Dict]) -> List[Dict]:
    """Remove records with null values."""
    return [r for r in records if all(v is not None for v in r.values())]


def normalize_strings(records: List[Dict]) -> List[Dict]:
    """Strip and lowercase all string values."""
    result = []
    for r in records:
        normalized = {}
        for k, v in r.items():
            normalized[k] = v.strip().lower() if isinstance(v, str) else v
        result.append(normalized)
    return result


def deduplicate(records: List[Dict], key: str) -> List[Dict]:
    """Remove duplicate records by key."""
    seen = set()
    result = []
    for r in records:
        val = r.get(key)
        if val not in seen:
            seen.add(val)
            result.append(r)
    return result
''')
    write_file(base, "loaders.py", '''"""Data loaders."""
import json
import csv
import os
from pathlib import Path
from typing import List, Dict


def load_json(filepath: str) -> List[Dict]:
    """Load records from JSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return [data]


def load_csv(filepath: str) -> List[Dict]:
    """Load records from CSV file."""
    records = []
    with open(filepath, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            records.append(dict(row))
    return records


def load_directory(dirpath: str, pattern: str = "*.json") -> List[Dict]:
    """Load all matching files from a directory."""
    all_records = []
    for fpath in sorted(Path(dirpath).glob(pattern)):
        all_records.extend(load_json(str(fpath)))
    return all_records
''')
    write_file(base, "analysis.py", '''"""Data analysis utilities."""
import statistics
from typing import List, Dict, Any, Optional
from collections import Counter


def compute_stats(values: List[float]) -> Dict[str, float]:
    """Compute basic statistics."""
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def frequency_table(values: List[Any]) -> List[Dict]:
    """Build frequency table sorted by count descending."""
    counter = Counter(values)
    total = len(values)
    return [
        {"value": val, "count": cnt, "pct": round(cnt / total * 100, 2)}
        for val, cnt in counter.most_common()
    ]


def group_by(records: List[Dict], key: str) -> Dict[str, List[Dict]]:
    """Group records by a key."""
    groups = {}
    for r in records:
        val = r.get(key, "unknown")
        groups.setdefault(val, []).append(r)
    return groups
''')


CATEGORY_A_GENERATORS = {
    "cli_tool": gen_cli_tool,
    "flask_app": gen_flask_app,
    "django_app": gen_django_app,
    "library": gen_library_package,
    "data_project": gen_data_project,
}


def test_category_a(tmp_path: Path) -> TestResults:
    """Category A: Clean repos -- parser stability, false positives, performance."""
    r = TestResults("Category A: Clean Real-Shaped Repos")

    for name, generator in CATEGORY_A_GENERATORS.items():
        repo_dir = tmp_path / name
        repo_dir.mkdir(parents=True)
        generator(repo_dir)

        # Scan
        code, output, elapsed = run_autonoma(repo_dir)
        r.check(f"[{name}] exit code 0", code == 0, f"got {code}")
        r.check(f"[{name}] no traceback", "Traceback" not in output)
        r.check(f"[{name}] completes in <5s", elapsed < 5.0, f"{elapsed:.2f}s")

        # JSON
        code_j, output_j, _ = run_autonoma(repo_dir, ["--format", "json"])
        r.check(f"[{name}] JSON exit 0", code_j == 0)
        try:
            payload = json.loads(output_j)
            issues = payload.get("issues", [])
            # Clean repos should have ZERO findings (all use os.getenv)
            r.check(f"[{name}] false positives: {len(issues)}", len(issues) == 0,
                    f"found {len(issues)}: {[i.get('message','') for i in issues[:3]]}")
        except json.JSONDecodeError:
            r.check(f"[{name}] valid JSON", False, "invalid JSON")

        # Dry-run should not crash
        code_d, output_d, _ = run_autonoma(repo_dir, ["--dry-run"])
        r.check(f"[{name}] dry-run no crash", "Traceback" not in output_d)

    return r


# ===========================================================================
# CATEGORY B: Seeded Benchmark Repos
# ===========================================================================

def gen_seeded_benchmark(base: Path):
    """Create benchmark repo with known detection/fix/refusal cases."""

    # .env.example for env contract
    write_file(base, ".env.example",
               "DB_PASSWORD=\nAPI_KEY=\nSENDGRID_KEY=\nSECRET_TOKEN=\nAWS_SECRET=\n")

    # --- File 1: obvious secrets (should DETECT + FIX) ---
    write_file(base, "secrets_obvious.py", '''"""File with obvious hardcoded secrets -- all should be FIXED."""
import os

db_password = "SuperSecret123!"
api_key = "sk-live-abc123xyz789def456"
secret_token = "ghp_1234567890abcdef1234567890abcdef12345678"
aws_secret = "AKIAIOSFODNN7EXAMPLE/wJalrXUtnFEMI"

def connect():
    pass
''')

    # --- File 2: safe patterns (should NOT detect or should SKIP) ---
    write_file(base, "already_safe.py", '''"""File with safe patterns -- should produce zero findings or SKIPPED."""
import os

db_password = os.getenv("DB_PASSWORD")
api_key = os.getenv("API_KEY", "")
token = os.environ.get("TOKEN")
secret = os.getenv("SECRET", None)

CONFIG_NAME = "production"
DEBUG_MODE = "false"
VERSION = "1.2.3"
EMPTY = ""
''')

    # --- File 3: ambiguous patterns (should REFUSE) ---
    write_file(base, "ambiguous_secrets.py", '''"""File with ambiguous patterns -- should be REFUSED."""
import os

# Single-letter variable -- can't infer env var name
x = "sk-live-abc123xyz789"

# Concatenated secret -- can't isolate
combined = "Bearer " + "sk-live-abc123"

# F-string usage -- too complex
prefix = "sk"
composed = f"{prefix}-live-key123"

def get_key():
    return "sk-live-test-key-123"
''')

    # --- File 4: test/example patterns (should SKIP or REFUSE) ---
    write_file(base, "test_helpers.py", '''"""Test helpers with placeholder secrets."""
import os

# Test fixtures -- these look like secrets but are test data
TEST_API_KEY = "test-api-key-not-real"
MOCK_PASSWORD = "mock-password-for-tests"

def setUp():
    password = "test_password_fixture"
    return password
''')

    # --- File 5: multi-assignment mixed file ---
    write_file(base, "config_mixed.py", '''"""Mixed config -- some fixable, some not."""
import os

# Fixable
admin_password = "RealAdminPass99!"

# Already safe
log_level = os.getenv("LOG_LEVEL", "INFO")

# Not a secret
app_name = "MyApplication"
version = "3.0.0"
max_retries = 5

# Fixable
sendgrid_key = "SG.real-sendgrid-api-key-here"
''')


# Expected outcomes for benchmark
BENCHMARK_EXPECTATIONS = {
    "secrets_obvious.py": {
        "min_findings": 3,
        "expected_fixes": ["FIXED"],  # At least some should be FIXED
    },
    "already_safe.py": {
        "max_findings": 0,
    },
    "ambiguous_secrets.py": {
        "expected_outcomes": ["REFUSED", "SKIPPED"],  # Should not be FIXED
    },
    "config_mixed.py": {
        "min_findings": 1,
        "has_fixed": True,
    },
}


def test_category_b(tmp_path: Path) -> TestResults:
    """Category B: Seeded benchmark -- detection, fixing, refusal correctness."""
    r = TestResults("Category B: Seeded Benchmark")

    repo_dir = tmp_path / "benchmark"
    repo_dir.mkdir(parents=True)
    gen_seeded_benchmark(repo_dir)

    # --- Detection test ---
    code, output, _ = run_autonoma(repo_dir, ["--format", "json"])
    r.check("Scan exit code 0", code == 0, f"got {code}")

    try:
        payload = json.loads(output)
        issues = payload.get("issues", [])

        # secrets_obvious.py should have detections
        obvious = [i for i in issues if "secrets_obvious" in i.get("file", "")]
        r.check("Detects secrets in secrets_obvious.py",
                len(obvious) >= 3, f"found {len(obvious)}")

        # already_safe.py should have ZERO detections
        safe = [i for i in issues if "already_safe" in i.get("file", "")]
        r.check("Zero findings in already_safe.py",
                len(safe) == 0, f"found {len(safe)}: {[s.get('message') for s in safe]}")

        # config_mixed.py should have some
        mixed = [i for i in issues if "config_mixed" in i.get("file", "")]
        r.check("Detects secrets in config_mixed.py",
                len(mixed) >= 1, f"found {len(mixed)}")

    except json.JSONDecodeError as e:
        r.check("JSON parse", False, str(e))

    # --- Fix test (on a copy) ---
    fix_dir = tmp_path / "benchmark_fix"
    shutil.copytree(repo_dir, fix_dir)

    code_f, output_f, _ = run_autonoma(fix_dir, ["--auto-fix", "--format", "json"])
    r.check("Auto-fix exit code 0", code_f == 0, f"got {code_f}")

    # Parse fix results
    try:
        # Split concatenated JSON objects
        json_blocks = []
        depth = 0
        start = 0
        for i, ch in enumerate(output_f):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    json_blocks.append(output_f[start:i+1])

        fix_data = None
        for block in json_blocks:
            try:
                parsed = json.loads(block)
                if "fix_results" in parsed:
                    fix_data = parsed
                    break
            except json.JSONDecodeError:
                continue

        if fix_data:
            results = fix_data["fix_results"]
            states = [fr["state"] for fr in results]

            r.check("Has FIXED outcomes", "FIXED" in states, f"states: {set(states)}")
            r.check("Has SKIPPED or REFUSED", "SKIPPED" in states or "REFUSED" in states)

            # All FIXED files must still be valid Python
            for fr in results:
                if fr["state"] == "FIXED":
                    fp = Path(fr["file"])
                    if fp.exists():
                        try:
                            import ast
                            ast.parse(fp.read_text(encoding="utf-8"))
                            r.check(f"FIXED file valid: {fp.name}", True)
                        except SyntaxError as e:
                            r.check(f"FIXED file valid: {fp.name}", False, str(e))

            # REFUSED should have reason codes
            refused = [fr for fr in results if fr["state"] == "REFUSED"]
            for fr in refused:
                r.check(f"REFUSED has reason: {fr.get('issue_id')}",
                        fr.get("reason") is not None and len(fr.get("reason", "")) > 0)

            # SKIPPED should have reason codes
            skipped = [fr for fr in results if fr["state"] == "SKIPPED"]
            for fr in skipped:
                r.check(f"SKIPPED has reason: {fr.get('issue_id')}",
                        fr.get("reason") is not None and len(fr.get("reason", "")) > 0)

        else:
            r.check("Fix results found", False, "no fix_results in output")

    except Exception as e:
        r.check("Fix results parsing", False, str(e))

    # Cleanup
    shutil.rmtree(fix_dir, ignore_errors=True)

    return r


# ===========================================================================
# CATEGORY C: Ugly / Adversarial Repos
# ===========================================================================

def gen_ugly_repo(base: Path):
    """Generate intentionally ugly/adversarial repo."""

    # 1. File with syntax errors
    write_file(base, "broken_syntax.py", '''"""This file has syntax errors."""
import os

def broken_func(
    # Missing closing paren and colon
    x = "password123"

class Broken
    pass
''')

    # 2. File with weird/mixed encodings (but valid UTF-8)
    write_file(base, "unicode_names.py", '''"""File with unicode in strings."""
import os

# These are normal strings, not secrets
greeting = "Hello"
message = "This is a normal message"
currency = "$100.00"
math_expr = "x = y + z"

def process():
    name = "Test User"
    return name
''')

    # 3. Deeply nested directory structure
    for depth in range(8):
        nested_path = "/".join([f"level_{i}" for i in range(depth + 1)])
        write_file(base, f"{nested_path}/__init__.py", '"""Nested."""\n')
        write_file(base, f"{nested_path}/module.py", f'''"""Module at depth {depth}."""
import os

value_{depth} = {depth * 100}

def func_{depth}():
    return value_{depth}
''')

    # 4. Very large file (1000+ lines of valid Python)
    big_lines = ['"""Very large auto-generated file."""', "import os", ""]
    for i in range(500):
        big_lines.append(f"var_{i} = {i * 7}")
        big_lines.append(f"list_{i} = [{i}, {i+1}, {i+2}]")
    write_file(base, "huge_file.py", "\n".join(big_lines))

    # 5. Empty file
    write_file(base, "empty.py", "")

    # 6. File with only comments
    write_file(base, "only_comments.py", '''# This file has only comments
# No actual code
# Just comments
# Line after line
# Nothing to scan
''')

    # 7. File with only docstring
    write_file(base, "only_docstring.py", '''"""
This module exists only as documentation.
It has no imports, no classes, no functions.
Just this docstring.
"""
''')

    # 8. File with many imports but no code
    write_file(base, "import_only.py", '''"""Imports only."""
import os
import sys
import json
import re
import hashlib
import logging
import collections
import itertools
import functools
import pathlib
import datetime
import typing
''')

    # 9. File with nested functions and closures
    write_file(base, "nested_closures.py", '''"""Deeply nested closures."""
import os


def outer():
    x = 10

    def middle():
        y = 20

        def inner():
            z = 30

            def deepest():
                return x + y + z

            return deepest()

        return inner()

    return middle()


def factory(name):
    def make_greeting(title):
        def format_greeting():
            return f"{title} {name}"
        return format_greeting
    return make_greeting
''')

    # 10. File with star imports and dynamic attrs
    write_file(base, "star_imports.py", '''"""Wild imports and dynamic attributes."""
import os
import sys

# Simulate dynamic attribute access
attrs = ["name", "value", "type"]
config = {}
for attr in attrs:
    config[attr] = os.getenv(attr.upper(), "default")

# Simulate computed variable names
for i in range(10):
    globals()[f"computed_var_{i}"] = i * 42
''')

    # 11. File masquerading with misleading names
    write_file(base, "password_utils.py", '''"""Utilities for password handling -- but no hardcoded passwords."""
import os
import hashlib

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
PASSWORD_CHARS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%"


def validate_password_strength(password: str) -> bool:
    if len(password) < PASSWORD_MIN_LENGTH:
        return False
    if len(password) > PASSWORD_MAX_LENGTH:
        return False
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    return has_upper and has_lower and has_digit


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()
''')

    # 12. Vendored-looking code in a nested vendor dir
    write_file(base, "vendor/third_party/__init__.py", '"""Vendored code."""\n')
    write_file(base, "vendor/third_party/legacy.py", '''"""Legacy vendored module."""
import os
import sys

# Vendored code often has hardcoded things -- tool should still handle it
LEGACY_VERSION = "0.9.3"
COMPAT_MODE = True

def legacy_init():
    return {"version": LEGACY_VERSION, "compat": COMPAT_MODE}
''')


def test_category_c(tmp_path: Path) -> TestResults:
    """Category C: Ugly repos -- resilience, no crashes."""
    r = TestResults("Category C: Ugly / Adversarial Repos")

    repo_dir = tmp_path / "ugly"
    repo_dir.mkdir(parents=True)
    gen_ugly_repo(repo_dir)

    # Must not crash
    code, output, elapsed = run_autonoma(repo_dir)
    r.check("No crash (exit 0)", code == 0, f"exit {code}")
    r.check("No traceback", "Traceback" not in output)
    r.check("Completes in <10s", elapsed < 10.0, f"{elapsed:.2f}s")
    r.check("Output has 'Analysis Complete'", "Analysis Complete" in output)

    # JSON must be valid
    code_j, output_j, _ = run_autonoma(repo_dir, ["--format", "json"])
    r.check("JSON exit 0", code_j == 0, f"exit {code_j}")
    try:
        payload = json.loads(output_j)
        r.check("JSON valid", True)
        files_scanned = payload.get("summary", {}).get("files_scanned", 0)
        r.check(f"Scanned {files_scanned} files (>0)", files_scanned > 0)
    except json.JSONDecodeError as e:
        r.check("JSON valid", False, str(e))

    # Dry-run must not crash
    code_d, output_d, _ = run_autonoma(repo_dir, ["--dry-run"])
    r.check("Dry-run no crash", "Traceback" not in output_d)

    # Auto-fix must not crash (even with broken files)
    fix_dir = tmp_path / "ugly_fix"
    shutil.copytree(repo_dir, fix_dir)
    code_af, output_af, _ = run_autonoma(fix_dir, ["--auto-fix"])
    r.check("Auto-fix no crash", "Traceback" not in output_af)
    r.check("Auto-fix completes", "Summary:" in output_af or "Analysis Complete" in output_af)

    # No file should be deleted
    pre_files = set(str(p.relative_to(repo_dir))
                    for p in repo_dir.rglob("*.py"))
    post_files = set(str(p.relative_to(fix_dir))
                     for p in fix_dir.rglob("*.py"))
    r.check("No files deleted after auto-fix", pre_files.issubset(post_files),
            f"missing: {pre_files - post_files}")

    # password_utils.py should NOT have false positives
    code_pw, output_pw, _ = run_autonoma(repo_dir / "password_utils.py", ["--format", "json"])
    try:
        pw_data = json.loads(output_pw)
        pw_issues = pw_data.get("issues", [])
        r.check("password_utils.py: no false positives",
                len(pw_issues) == 0,
                f"found {len(pw_issues)}: {[i.get('message') for i in pw_issues]}")
    except json.JSONDecodeError:
        r.check("password_utils.py JSON valid", False)

    # Cleanup
    shutil.rmtree(fix_dir, ignore_errors=True)

    return r


# ===========================================================================
# Main
# ===========================================================================

def main():
    print("=" * 60)
    print("Autonoma -- Three-Category Repo Test Suite")
    print("=" * 60)

    all_results = []

    with tempfile.TemporaryDirectory(prefix="autonoma_cat_") as tmp_path:
        tmppath = Path(tmp_path)

        # Category A
        print(f"\n{'-'*60}")
        print("Category A: Clean Real-Shaped Repos")
        print(f"{'-'*60}")
        ra = test_category_a(tmppath / "cat_a")
        all_results.append(ra)
        print(ra.summary())

        # Category B
        print(f"\n{'-'*60}")
        print("Category B: Seeded Benchmark")
        print(f"{'-'*60}")
        rb = test_category_b(tmppath / "cat_b")
        all_results.append(rb)
        print(rb.summary())

        # Category C
        print(f"\n{'-'*60}")
        print("Category C: Ugly / Adversarial Repos")
        print(f"{'-'*60}")
        rc = test_category_c(tmppath / "cat_c")
        all_results.append(rc)
        print(rc.summary())

    # Final summary
    total_pass = sum(r.passed for r in all_results)
    total_fail = sum(r.failed for r in all_results)
    print(f"\n{'='*60}")
    print(f"FINAL: {total_pass} passed, {total_fail} failed")
    if total_fail == 0:
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES DETECTED ({total_fail})")
    print(f"{'='*60}")

    sys.exit(1 if total_fail > 0 else 0)


if __name__ == "__main__":
    main()
