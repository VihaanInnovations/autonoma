"""
Autonoma — Tests for .autonomaignore
"""
from pathlib import Path
from autonoma.engine import AnalysisEngine


def test_autonomaignore_file_excluded(tmp_path: Path):
    """If a file matches a pattern in .autonomaignore, it should be skipped."""
    # Create structure
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("API_KEY = 'sk_live_1234567890'\n")
    
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "example.py").write_text("API_KEY = 'sk_live_0987654321'\n")
    
    # Write ignore file
    ignore_file = tmp_path / ".autonomaignore"
    ignore_file.write_text("# ignore docs\ndocs/*\n")
    
    # Run analysis
    engine = AnalysisEngine(allowed_extensions={".py"})
    report = engine.run(tmp_path)
    
    # Should only scan 1 file (src/app.py) because docs/* is ignored
    assert report.files_scanned == 1
    assert report.total_issues == 1
    assert "src\\app.py" in str(report.file_results[0].file) or "src/app.py" in str(report.file_results[0].file)
    
    
def test_autonomaignore_merges_with_exclude_flag(tmp_path: Path):
    """Patterns from .autonomaignore should merge with explicitly passed CLI --exclude patterns."""
    f1 = tmp_path / "skip_me.py"
    f1.write_text("pwd='xxx'\n")
    
    f2 = tmp_path / "ignore_too.py"
    f2.write_text("pwd='yyy'\n")
    
    f3 = tmp_path / "scan_me.py"
    f3.write_text("print('hello')\n")
    
    # Ignore one via file
    (tmp_path / ".autonomaignore").write_text("skip_me.py\n")
    
    engine = AnalysisEngine(allowed_extensions={".py"})
    # Ignore the other via CLI flag
    report = engine.run(tmp_path, exclude_patterns=["ignore_too.py"])
    
    assert report.files_scanned == 1
    assert report.total_issues == 0
    assert "scan_me.py" in str(report.file_results[0].file)
