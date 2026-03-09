"""
Autonoma — Tests for CI Mode
"""
from pathlib import Path
from click.testing import CliRunner
from autonoma.cli import analyze


def test_ci_mode_clean_exits_0(tmp_path: Path):
    """If no issues are found, --ci should exit 0."""
    repo = tmp_path / "repo"
    repo.mkdir()
    
    clean_py = repo / "clean.py"
    clean_py.write_text("print('hello world')\n")
    
    runner = CliRunner()
    result = runner.invoke(analyze, [str(repo), "--ci"])
    
    # 0 = clean
    assert result.exit_code == 0


def test_ci_mode_fixable_exits_2(tmp_path: Path):
    """If HIGH severity SEC001 or SEC002 are found, --ci should exit 2."""
    repo = tmp_path / "repo"
    repo.mkdir()
    
    vuln_py = repo / "vuln.py"
    vuln_py.write_text("API_KEY = 'ak_live_1234567890'\n")
    
    runner = CliRunner()
    result = runner.invoke(analyze, [str(repo), "--ci"])
    
    # 2 = fixable secrets found
    assert result.exit_code == 2


def test_ci_mode_unfixable_exits_1(tmp_path: Path):
    """
    If issues are found but NONE are fixable (e.g., non-SEC001/SEC002 or low severity),
    --ci should exit 1.
    We simulate this by putting an issue inside a file but manually disabling SEC002,
    or relying on a placeholder heuristic if one existed. Actually, the easiest way
    is to trigger a different issue type or severity. 
    Currently SEC001/SEC002 are the only rules and both are HIGH.
    To test exit 1, we can mock the engine report.
    """
    from autonoma.engine import AnalysisEngine, AnalysisReport, FileResult
    
    # Create a mock report with an unfixable issue (e.g., medium severity or SEC003)
    mock_report = AnalysisReport(
        files_scanned=1,
        total_issues=1,
        high_count=0,
        file_results=[
            FileResult(
                file="x.py", 
                abs_path="/x.py", 
                issues=[{"id": "SEC999", "severity": "medium", "message": "Fake"}]
            )
        ]
    )
    
    # Monkeypatch the engine's run method to return our mock report
    class MockEngine(AnalysisEngine):
        def run(self, *args, **kwargs):
            return mock_report
            
    import autonoma.cli
    original_engine = autonoma.cli.AnalysisEngine
    autonoma.cli.AnalysisEngine = MockEngine
    
    try:
        runner = CliRunner()
        repo = tmp_path / "repo"
        repo.mkdir()
        
        # File must exist to pass Click path validation
        (repo / "test.py").write_text("print(1)")
        
        result = runner.invoke(analyze, [str(repo), "--ci"])
        
        # 1 = secrets detected but non-fixable
        assert result.exit_code == 1
    finally:
        autonoma.cli.AnalysisEngine = original_engine
