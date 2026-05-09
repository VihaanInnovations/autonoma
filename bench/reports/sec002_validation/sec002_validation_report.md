# SEC002 Value-Gate Validation Report

**Date:** 2026-05-06  
**Autonoma version:** 0.1.8  
**Change validated:** SEC002 value-side gate fix  
**Note:** No detection or remediation logic was changed during this validation.

## A. Summary Table — All 10 Repos

| Repo | Total | SEC001 | SEC002 | Other | Safe-to-Fix | Refused |
|------|-------|--------|--------|-------|-------------|---------|
| flask | 0 | 0 | 0 | 0 | 0 | 0 |
| requests | 0 | 0 | 0 | 0 | 0 | 0 |
| httpx | 0 | 0 | 0 | 0 | 0 | 0 |
| fastapi | 12 | 6 | 6 | 0 | 0 | 12 |
| django | 7 | 1 | 6 | 0 | 0 | 7 |
| sqlalchemy | 18 | 15 | 3 | 0 | 0 | 18 |
| pydantic | 6 | 4 | 2 | 0 | 0 | 4 |
| celery | 6 | 0 | 6 | 0 | 0 | 6 |
| black | 1 | 0 | 1 | 0 | 0 | 1 |
| mypy | 0 | 0 | 0 | 0 | 0 | 0 |
| **TOTAL** | **50** | | | | | |

## B. Original 5 Repos — Before / After Comparison

| Repo | Old Count | New Count | Delta | Likely Removed Noise |
|------|-----------|-----------|-------|----------------------|
| flask | 0 | 0 | +0 | 0 |
| requests | 0 | 0 | +0 | 0 |
| httpx | 1 | 0 | -1 | 1 |
| fastapi | 23 | 12 | -11 | 11 |
| django | 13 | 7 | -6 | 6 |
| **Total** | **37** | **19** | **-18** | **18** |

No precision claim is made from these raw counts.
This does not imply measured precision improvement — human label review is required.
The reduction is consistent with known false-positive patterns being suppressed.

## C. Unseen 5 Repos — New Results

| Repo | Total | SEC001 | SEC002 |
|------|-------|--------|--------|
| sqlalchemy | 18 | 15 | 3 |
| pydantic | 6 | 4 | 2 |
| celery | 6 | 0 | 6 |
| black | 1 | 0 | 1 |
| mypy | 0 | 0 | 0 |
| **Total** | **31** | | |

## D. Top SEC002 Findings (up to 20)

| # | Repo | File:Line | Context | Assessment |
|---|------|-----------|---------|------------|
| 1 | fastapi | `docs_src/app_testing/app_b_an_py310/main.py:6` | `fake_secret_token = "coneofsilence"` | FP_DOC — FastAPI tutorial fake token |
| 2 | fastapi | `docs_src/app_testing/app_b_py310/main.py:4` | `fake_secret_token = "coneofsilence"` | FP_DOC — FastAPI tutorial fake token |
| 3 | fastapi | `docs_src/security/tutorial004_an_py310.py:13` | `SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"` | TP_DOC — tutorial JWT secret (realistic, in docs) |
| 4 | fastapi | `docs_src/security/tutorial004_py310.py:12` | `SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"` | TP_DOC — tutorial JWT secret (realistic, in docs) |
| 5 | fastapi | `docs_src/security/tutorial005_an_py310.py:17` | `SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"` | TP_DOC — tutorial JWT secret (realistic, in docs) |
| 6 | fastapi | `docs_src/security/tutorial005_py310.py:16` | `SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"` | TP_DOC — tutorial JWT secret (realistic, in docs) |
| 7 | django | `django/core/checks/security/base.py:25` | `SECRET_KEY_WARNING_MSG = (` | FP — metadata variable, not a credential |
| 8 | django | `django/middleware/csrf.py:346` | `token_source = f"the {header_name!r} HTTP header"` | FP — f-string path template |
| 9 | django | `django/template/base.py:385` | `return '<%s token: "%s...">' % (` | REVIEW |
| 10 | django | `django/template/base.py:745` | `>>> token = 'variable\|default:"Default value"\|date:"Y-m-d"'` | FP — docstring example line |
| 11 | django | `docs/_ext/djangodocs.py:313` | `token = "%HOMEPATH%\\" + token[2:]` | REVIEW |
| 12 | django | `docs/_ext/djangodocs.py:316` | `token = "make.bat"` | FP — file path value |
| 13 | sqlalchemy | `examples/sharding/separate_schema_translates.py:204` | `identity_token="asia",` | FP — short geographic sharding token |
| 14 | sqlalchemy | `lib/sqlalchemy/connectors/pyodbc.py:81` | `token = "{%s}" % token.replace("}", "}}")` | FP — format template, not a credential |
| 15 | sqlalchemy | `lib/sqlalchemy/dialects/mssql/mssqlpython.py:119` | `token = "{%s}" % token.replace("}", "}}")` | FP — format template, not a credential |
| 16 | pydantic | `.github/actions/people/action.yml:28` | `INPUT_TOKEN: ${{ inputs.token }}` | FP — GitHub Actions expression reference |
| 17 | pydantic | `.github/workflows/third-party.yml:381` | `SECRET_ACCESS_KEY: polar123456789` | FP_PLACEHOLDER — obvious test credential |
| 18 | celery | `examples/celery_http_gateway/settings.py:70` | `SECRET_KEY = 'This is not a secret, be sure to change this.'` | FP — explicit placeholder message |
| 19 | celery | `examples/django/proj/settings.py:40` | `SECRET_KEY = 'l!t+dmzf97rt9s*yrsux1py_1@odvz1szr&6&m!f@-nxq6k%%p'` | TP_DOC — realistic Django SECRET_KEY in example settings |
| 20 | celery | `helm-chart/templates/serviceaccount.yaml:13` | `automountServiceAccountToken: {{ .Values.serviceAccount.automount }}` | FP — YAML boolean field |

## E. Suppression-Risk Assessment

### Limitation
Without pre-gate instrumentation, suppressed findings cannot be directly enumerated.
The table below identifies assignments in non-test, non-doc production code that matched
a secret-variable naming pattern but did NOT appear in scanner findings.

### Suspicious Non-Flagged Assignments (unseen repos, production code)

| Repo | File | Line | Assignment | Assessment |
|------|------|------|------------|------------|
| sqlalchemy | lib/sqlalchemy/orm/path_registry.py | 86 | `TOKEN = "_sa_default"` | Correct suppression — underscore-prefix internal token name |
| pydantic | pydantic/types.py | 1825 | `password='password1'` | Correct suppression — value mirrors variable name |
| pydantic | pydantic/types.py | 1852 | `password='IAmSensitive'` | **Review needed** — not excluded by gates; likely in docstring/example |
| celery | t/unit/backends/test_mongodb.py | 48 | `PASSWORD = 'celerypassword'` | Correct exclusion — test file |
| celery | t/unit/backends/test_redis.py | 397 | `password = 'password'` | Correct exclusion — test file |

**Assessment:** 4 of 5 cases are correctly suppressed or excluded.
One case (`pydantic/types.py password='IAmSensitive'`) warrants manual inspection
to confirm it is in a docstring/type annotation example, not operational code.

### Original 6 Known False Positives — Confirmed Absent

| Pattern | Present in any finding? |
|---------|-------------------------|
| `token = "is not"` | No |
| `token = "not in"` | No |
| `token_source = "POST"` | No |
| `INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"` | No |
| `tokenUrl = "token"` | No |
| `apiKey = "apiKey"` | No |

## Precision Statement

_Raw finding count changed from 37 to 19 for the original 5 repos._  
_No precision claim is made from raw counts._  
_Human review of `findings_suggested.csv` is required before any precision claim._  
_The suppression changes are consistent with removing known noise patterns._

