"""
Autonoma — Git Utilities

Lightweight subprocess wrappers for Git operations.
We avoid third-party dependencies (like GitPython) to keep the footprint small.
"""
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional


@dataclass
class AddedLine:
    """Represents a single line of text added in a diff."""
    line_number: int
    content: str


@dataclass
class FileDiff:
    """Represents the changes to a single file in a commit."""
    file_path: str
    added_lines: List[AddedLine] = field(default_factory=list)


@dataclass
class GitCommit:
    """Represents a single Git commit and its relevant file diffs."""
    hash: str
    author_date: str
    message: str
    file_diffs: List[FileDiff] = field(default_factory=list)


def parse_git_log_p(repo_path: Path, allowed_extensions: set[str]) -> Iterator[GitCommit]:
    """
    Run `git log -p -U0` and parse the output.
    Yields GitCommit objects containing only the lines *added* to files
    with supported extensions.

    -U0 ensures we don't get context lines, keeping the output small and fast.
    """
    cmd = [
        "git",
        "log",
        "-p",
        "-U0",
        "--no-color",
        "--format=COMMIT|%H|%cd|%s",
        "--date=iso-strict",
    ]

    try:
        process = subprocess.Popen(
            cmd,
            cwd=repo_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
    except FileNotFoundError:
        # Git is not installed or not in PATH
        return
    except Exception:
        return

    current_commit: Optional[GitCommit] = None
    current_file: Optional[FileDiff] = None
    current_line_num = 0

    for line in process.stdout:
        line = line.rstrip("\n")

        # 1. New commit boundary
        if line.startswith("COMMIT|"):
            if current_commit and any(f.added_lines for f in current_commit.file_diffs):
                yield current_commit

            parts = line.split("|", 3)
            # Safe unpack in case message contains pipes
            commit_hash = parts[1] if len(parts) > 1 else "unknown"
            author_date = parts[2] if len(parts) > 2 else "unknown"
            message = parts[3] if len(parts) > 3 else ""

            current_commit = GitCommit(hash=commit_hash, author_date=author_date, message=message)
            current_file = None
            continue

        if not current_commit:
            continue

        # 2. New file boundary in diff
        # Format: +++ b/path/to/file.py
        if line.startswith("+++ b/"):
            file_path = line[6:]
            ext = Path(file_path).suffix.lower()

            if ext in allowed_extensions:
                current_file = FileDiff(file_path=file_path)
                current_commit.file_diffs.append(current_file)
            else:
                # Ignore this file's diff lines
                current_file = None
            continue

        if not current_file:
            continue

        # 3. Hunk header (to track line numbers)
        # Format: @@ -10,0 +11,3 @@
        if line.startswith("@@ "):
            try:
                # Extract the +11,3 part
                plus_part = line.split(" ")[2]
                # It might be +11 or +11,3
                start_line = plus_part.split(",")[0].replace("+", "")
                current_line_num = int(start_line)
            except Exception:
                current_line_num = 0
            continue

        # 4. Added lines
        if line.startswith("+") and not line.startswith("+++"):
            # The actual line content, stripping the leading '+'
            content = line[1:]
            current_file.added_lines.append(
                AddedLine(line_number=current_line_num, content=content)
            )
            current_line_num += 1

    # Yield the last commit if it had anything
    if current_commit and any(f.added_lines for f in current_commit.file_diffs):
        yield current_commit

    process.wait()
