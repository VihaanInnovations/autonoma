import pytest
from pathlib import Path
from autonoma._internal.ast_engine import ASTEngine
from autonoma._internal.secret_fixer import SecretFixer

@pytest.fixture
def ast_engine():
    return ASTEngine()

@pytest.fixture
def secret_fixer(tmp_path):
    # Create a dummy .env.example to satisfy env contract
    (tmp_path / ".env.example").write_text("API_KEY=dummy\nPASSWORD=dummy\n")
    return SecretFixer(repo_path=tmp_path)


def test_idempotency_guarantee(secret_fixer, ast_engine):
    """Prove that running the fixer twice causes exactly 0 changes on the second run."""
    original_code = 'API_KEY = "sk-live-1234"\n'
    
    # Run 1: Apply the patch
    issues1 = ast_engine.analyze(original_code, "test.py")
    assert len(issues1) == 1
    result1 = secret_fixer.fix_file(original_code, Path("test.py"), issues1)
    assert result1.any_fixed
    fixed_code = result1.fixed_code
    
    # Run 2: Feed output back into the engine
    issues2 = ast_engine.analyze(fixed_code, "test.py")
    
    # The native engine is smart enough to ignore os.environ constructs natively
    assert len(issues2) == 0
    
    # Even if passed directly to the fixer, the fixer should treat it as already safe
    # Let's fake an issue finding to prove the fixer's secondary defense line:
    fake_issue = [{"id": "SEC001", "line": 2, "col_offset": 10}]
    result2 = secret_fixer.fix_file(fixed_code, Path("test.py"), fake_issue)
    
    assert not result2.any_fixed
    assert result2.fixed_code is None


def test_import_safety_guarantee(secret_fixer, ast_engine):
    """Prove missing imports, duplicate imports, and shadowed namespaces are handled safely."""
    
    # Scenario A: Missing Import -> Injected Safely
    code_missing = 'API_KEY = "sk-live-1234"\n'
    issues_a = ast_engine.analyze(code_missing, "test.py")
    res_a = secret_fixer.fix_file(code_missing, Path("test.py"), issues_a)
    assert res_a.any_fixed
    assert "import os\nAPI_KEY" in res_a.fixed_code
    
    # Scenario B: Duplicate Import -> Reused (No Duplicates)
    code_duplicate = 'import os\nAPI_KEY = "sk-live-1234"\n'
    issues_b = ast_engine.analyze(code_duplicate, "test.py")
    res_b = secret_fixer.fix_file(code_duplicate, Path("test.py"), issues_b)
    assert res_b.any_fixed
    assert res_b.fixed_code.count("import os") == 1
    
    # Scenario C: Shadowed Namespace -> REFUSED safely
    code_shadowed = 'os = "Operating System"\nAPI_KEY = "sk-live-1234"\n'
    issues_c = ast_engine.analyze(code_shadowed, "test.py")
    res_c = secret_fixer.fix_file(code_shadowed, Path("test.py"), issues_c)
    assert not res_c.any_fixed
    assert res_c.per_issue[0].outcome == "REFUSED"
    assert res_c.per_issue[0].reason == "refuse_os_shadowed"


def test_minimal_diff_guarantee(secret_fixer, ast_engine):
    """Prove that messy whitespace, indentation, and comments are perfectly preserved."""
    original_code = 'def connect():\n    # legacy auth stuff\n    api_key   =   "sk-live-messy"  # SEC002\n'
    issues = ast_engine.analyze(original_code, "test.py")
    result = secret_fixer.fix_file(original_code, Path("test.py"), issues)
    
    assert result.any_fixed
    
    # Verify EXACT spacing and comments minus the literal replacement
    patched_lines = result.fixed_code.splitlines()
    assert patched_lines[0] == 'import os'
    assert patched_lines[2] == '    # legacy auth stuff'
    assert patched_lines[3] == '    api_key   =   os.environ["API_KEY"]  # SEC002'
