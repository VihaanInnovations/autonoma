"""
Seeder for Autonoma synthetic positive controls.

Takes a private controls manifest and distributes the controls into a LOCAL
clone of a target repository across multiple file formats and syntactic
positions. Records exact seed locations into a seed_log.json so recall can
be measured by matching detector hits against known seed locations.

CRITICAL: Operate on local clones only. Never push a seeded clone to a
public remote. The seeder will refuse to run in a directory whose git
remote points to a public host (best-effort safety check; not foolproof).

Usage:
    python seeder.py \\
        --manifest controls_manifest.json \\
        --target-repo /local/path/to/cloned-repo \\
        --seed-log seed_log.json \\
        --rng-seed 42
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Safety: refuse to run on a clone with a public remote
# ---------------------------------------------------------------------------

PUBLIC_REMOTE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org")


def assert_local_only(repo_path: Path) -> None:
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "-v"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return

    remotes = result.stdout
    for host in PUBLIC_REMOTE_HOSTS:
        if host in remotes:
            print(
                f"REFUSING TO SEED: target repo has a remote pointing to {host}.\n"
                f"Remotes:\n{remotes}\n"
                f"Remove the remote or work on a clone with no public remote.",
                file=sys.stderr,
            )
            sys.exit(3)


# ---------------------------------------------------------------------------
# Format-specific renderers
# Each renderer takes a Control and returns a string snippet to insert.
# ---------------------------------------------------------------------------

def render_python(family: str, value: str, var_name: str) -> str:
    if family == "aws_pair":
        access, secret = value.split("|", 1)
        return (
            f'{var_name}_access_key = "{access}"\n'
            f'{var_name}_secret_key = "{secret}"\n'
        )
    if family == "pem_private":
        return f'{var_name} = """{value}"""\n'
    return f'{var_name} = "{value}"\n'


def render_yaml(family: str, value: str, var_name: str) -> str:
    if family == "aws_pair":
        access, secret = value.split("|", 1)
        return (
            f"{var_name}:\n"
            f"  access_key_id: {access}\n"
            f"  secret_access_key: {secret}\n"
        )
    if family == "pem_private":
        indented = "\n".join("  " + line for line in value.splitlines())
        return f"{var_name}: |\n{indented}\n"
    return f"{var_name}: {value}\n"


def render_json(family: str, value: str, var_name: str) -> str:
    if family == "aws_pair":
        access, secret = value.split("|", 1)
        obj = {var_name: {"access_key_id": access, "secret_access_key": secret}}
    else:
        obj = {var_name: value}
    return json.dumps(obj, indent=2) + "\n"


def render_env(family: str, value: str, var_name: str) -> str:
    upper = var_name.upper()
    if family == "aws_pair":
        access, secret = value.split("|", 1)
        return f"{upper}_ACCESS_KEY_ID={access}\n{upper}_SECRET_ACCESS_KEY={secret}\n"
    if family == "pem_private":
        escaped = value.replace("\n", "\\n")
        return f'{upper}="{escaped}"\n'
    return f"{upper}={value}\n"


def render_markdown(family: str, value: str, var_name: str) -> str:
    if family == "aws_pair":
        access, secret = value.split("|", 1)
        return (
            f"## Configuration: {var_name}\n\n"
            f"Set your access key:\n\n"
            f"```\n{access}\n```\n\n"
            f"And your secret:\n\n"
            f"```\n{secret}\n```\n"
        )
    if family == "pem_private":
        return f"## Private Key: {var_name}\n\n```\n{value}\n```\n"
    return f"## {var_name}\n\nExample value:\n\n```\n{value}\n```\n"


FORMAT_RENDERERS = {
    "python": (render_python, ".py"),
    "yaml": (render_yaml, ".yaml"),
    "json": (render_json, ".json"),
    "env": (render_env, ".env"),
    "markdown": (render_markdown, ".md"),
}

# Weighted format distribution. Deterministic under RNG seed via random.choices.
FORMAT_WEIGHTS = [
    ("python",   0.35),
    ("yaml",     0.25),
    ("env",      0.20),
    ("json",     0.15),
    ("markdown", 0.05),
]

# Realistic repo-like subdirectories. Selected deterministically per-control.
# Avoids benchmark-named directories to reduce contamination signatures.
SEED_PATH_PREFIXES = [
    "docs/examples",
    "config",
    "scripts",
    "deploy",
    ".github/workflows",
    "tests/fixtures",
    "env",
    "examples",
    "samples",
]


# ---------------------------------------------------------------------------
# Variable name patterns by family (for credential-shaped naming)
# ---------------------------------------------------------------------------

VAR_NAMES = {
    "stripe": ["stripe_secret_key", "stripe_api_key", "payment_secret"],
    "github_pat": ["github_token", "gh_pat", "github_api_token"],
    "aws_pair": ["aws", "production_aws", "s3_credentials"],
    "google_api": ["google_api_key", "gcp_key", "maps_api_key"],
    "slack_bot": ["slack_bot_token", "slack_token", "notify_token"],
    "jwt": ["session_jwt", "auth_token", "id_token"],
    "pem_private": ["server_private_key", "rsa_private_key", "tls_key"],
    "generic_bearer": ["bearer_token", "api_bearer", "auth_bearer"],
    "opaque_api_secret": ["api_secret", "service_secret", "client_secret"],
    "opaque_session_token": ["session_token", "user_session", "access_session"],
    "opaque_random_cred": ["credential", "auth_credential", "service_credential"],
}


# ---------------------------------------------------------------------------
# Seed log
# ---------------------------------------------------------------------------

@dataclass
class SeedLocation:
    control_id: str
    family: str
    file_path: str  # relative to repo root
    file_format: str
    var_name: str
    expected_value: str  # the string the detector should find


@dataclass
class SeedLog:
    schema_version: str
    rng_seed: int
    manifest_seed: int
    target_repo: str
    seeded_at: str
    locations: list[SeedLocation]

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "rng_seed": self.rng_seed,
            "manifest_seed": self.manifest_seed,
            "target_repo": self.target_repo,
            "seeded_at": self.seeded_at,
            "locations": [asdict(loc) for loc in self.locations],
        }


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------

def list_cleanup_dirs(locations: list[SeedLocation], repo_root: Path) -> list[str]:
    """Return sorted unique top-level directories that contain seeded files."""
    top_dirs: set[str] = set()
    for loc in locations:
        parts = Path(loc.file_path).parts
        if parts:
            top_dirs.add(str(repo_root / parts[0]))
    return sorted(top_dirs)


# ---------------------------------------------------------------------------
# Seeding logic
# ---------------------------------------------------------------------------

def seed_one(
    rng: random.Random,
    repo_root: Path,
    control: dict,
) -> SeedLocation:
    family = control["family"]
    value = control["value"]
    control_id = control["id"]

    fmt_names = [f for f, _ in FORMAT_WEIGHTS]
    weights = [w for _, w in FORMAT_WEIGHTS]
    fmt_name = rng.choices(fmt_names, weights=weights, k=1)[0]
    renderer, ext = FORMAT_RENDERERS[fmt_name]

    var_names = VAR_NAMES.get(family, ["api_key", "secret_key", "token"])
    var_name = rng.choice(var_names)

    snippet = renderer(family, value, var_name)

    path_prefix = rng.choice(SEED_PATH_PREFIXES)
    seed_subdir = repo_root / path_prefix
    seed_subdir.mkdir(parents=True, exist_ok=True)
    target_file = seed_subdir / f"{control_id}{ext}"
    target_file.write_text(snippet)

    return SeedLocation(
        control_id=control_id,
        family=family,
        file_path=str(target_file.relative_to(repo_root)),
        file_format=fmt_name,
        var_name=var_name,
        expected_value=value,
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Seed Autonoma synthetic controls into a local repo clone.")
    p.add_argument("--manifest", type=Path, required=True, help="Private controls manifest from generator.py")
    p.add_argument("--target-repo", type=Path, required=True, help="Path to LOCAL clone (no public remote)")
    p.add_argument("--seed-log", type=Path, required=True, help="Output path for seed_log.json")
    p.add_argument("--rng-seed", type=int, required=True, help="RNG seed for placement decisions")
    p.add_argument("--allow-public-remote", action="store_true", help="DANGEROUS: skip the public-remote check")
    args = p.parse_args()

    if not args.target_repo.is_dir():
        print(f"Target repo not found: {args.target_repo}", file=sys.stderr)
        return 2

    if not args.allow_public_remote:
        assert_local_only(args.target_repo)

    manifest = json.loads(args.manifest.read_text())
    if any(
        c["value"].startswith("<REDACTED")
        for c in manifest["controls"]
    ):
        print(
            "Manifest contains redacted values. Regenerate the private manifest "
            "with generator.py before seeding.",
            file=sys.stderr,
        )
        return 2

    rng = random.Random(args.rng_seed)
    locations: list[SeedLocation] = []
    for control in manifest["controls"]:
        loc = seed_one(rng, args.target_repo, control)
        locations.append(loc)

    log = SeedLog(
        schema_version="1.0",
        rng_seed=args.rng_seed,
        manifest_seed=manifest["seed"],
        target_repo=str(args.target_repo.resolve()),
        seeded_at=datetime.now(timezone.utc).isoformat(),
        locations=locations,
    )

    args.seed_log.parent.mkdir(parents=True, exist_ok=True)
    args.seed_log.write_text(json.dumps(log.to_dict(), indent=2))
    print(f"Seeded {len(locations)} controls into {args.target_repo}")
    print(f"Seed log: {args.seed_log}")

    cleanup_dirs = list_cleanup_dirs(locations, args.target_repo)
    print("Cleanup (remove seeded directories):")
    for d in cleanup_dirs:
        print(f"  rm -rf {d}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
