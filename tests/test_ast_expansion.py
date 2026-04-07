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
    (tmp_path / ".env.example").write_text("API_KEY=dummy")
    return SecretFixer(repo_path=tmp_path)

def test_detect_keyword_argument(ast_engine):
    code = 'client.connect(password="super_secret_123")'
    issues = ast_engine.analyze(code, "test.py")
    
    assert len(issues) == 1
    assert issues[0]["id"] == "SEC001"
    assert issues[0]["pattern_type"] == "password"
    assert "password" in issues[0]["message"]

def test_refuse_kwargs_unpacking(ast_engine):
    code = 'client.connect(**{"password": "supersecret"})'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_refuse_kwargs_fstring(ast_engine):
    code = 'connect(password=f"{prefix}-secret")'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 1

def test_refuse_kwargs_binop(ast_engine):
    code = 'connect(password="sec" + "ret")'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_refuse_kwargs_call(ast_engine):
    code = 'connect(password=get_password())'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_detect_class_attribute(ast_engine):
    code = """
class Config:
    ADMIN_PASSWORD = "prod_password_abc"
    API_KEY = "sk-1234567890"
"""
    issues = ast_engine.analyze(code, "test.py")
    
    # We should have 2 issues
    assert len(issues) == 2
    assert any(i["id"] == "SEC001" for i in issues)
    assert any(i["id"] == "SEC002" for i in issues)

def test_refuse_nested_class_assignment(ast_engine):
    code = """
class Config:
    if True:
        ADMIN_PASSWORD = "prod_password_abc"
"""
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 1
    assert issues[0]["id"] == "SEC001"

def test_refuse_class_attribute_fstring(ast_engine):
    code = 'class Settings: API_KEY = f"{prefix}_secret"'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 1

def test_refuse_class_attribute_getenv(ast_engine):
    code = 'class Settings: API_KEY = os.getenv("API_KEY", "fallback-secret")'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_refuse_class_attribute_binop(ast_engine):
    code = 'class Settings: API_KEY = SECRET_PREFIX + "abc"'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_refuse_class_attribute_multitarget(ast_engine):
    code = 'class Settings: A = B = "supersecret"'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_fix_keyword_argument(secret_fixer, ast_engine):
    code = 'client.connect(api_key="sk-1234567890")'
    issues = ast_engine.analyze(code, "test.py")
    
    result = secret_fixer.fix_file(code, Path("test.py"), issues)
    
    assert result.any_fixed
    # Confirm name preservation
    assert 'api_key=os.environ["API_KEY"]' in result.fixed_code
    # Confirm raw secret sk-1234567890 does NOT appear
    assert 'sk-1234567890' not in result.fixed_code

def test_fix_class_attribute(secret_fixer, ast_engine):
    # FINAL PRE-TAG MANUAL CHECK (CLASS ATTRIBUTE)
    code = """class Settings:
    API_KEY = "sk-live-abc"
"""
    issues = ast_engine.analyze(code, "test.py")
    
    result = secret_fixer.fix_file(code, Path("test.py"), issues)
    
    assert result.any_fixed
    # Confirm transformation
    assert 'API_KEY = os.environ["API_KEY"]' in result.fixed_code
    # Confirm raw secret sk-live-abc does NOT appear
    assert 'sk-live-abc' not in result.fixed_code

def test_strict_refuse_multiple_targets(ast_engine):
    code = 'PASSWORD = PWD = "secret123"'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_strict_refuse_tuple_unpacking(ast_engine):
    code = 'API_KEY, PASSWORD = "sk-123", "secret123"'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_strict_refuse_attribute_target(ast_engine):
    code = 'self.PASSWORD = "secret123"'
    issues = ast_engine.analyze(code, "test.py")
    assert len(issues) == 0

def test_detect_os_environ_assignment(ast_engine):
    code = 'os.environ["DB_PASSWORD"] = "secret123"'
    issues = ast_engine.analyze(code, "test.py")
    
    assert len(issues) == 1
    assert issues[0]["id"] == "SEC001"
