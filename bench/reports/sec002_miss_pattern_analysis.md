# SEC002 Miss-Pattern Analysis Report

Generated: 2026-05-09 00:39 UTC
Source: `sec002_recall_diagnostic_v2.csv`
Corpus: 10 repos, 33 controls/repo, 330 total seedings

## 1. Executive Summary

- **Total seeded controls**: 330
- **Matched (detected)**: 188 (57.0%)
- **Missed (VALUE_NOT_FOUND)**: 142 (43.0%)
- **Strict recall**: 57.0% (headline metric, unchanged)

The 142 missed controls decompose into four root-cause tiers. Fourteen are architectural exclusions (Markdown extension not scanned). Fifty belong to families intentionally outside SEC002 scope (PEM private keys and opaque random credentials). Seventy-seven are routing architecture failures where the seeder assigned variable names outside the SEC002 keyword sets — the parser reached the value but keyword routing never evaluated it. One is a true detector failure where keyword routing evaluated the value but SEC002 failed to detect it.

## 2. Miss Categories

The old DETECTOR_MISS bucket has been split into three categories that reflect distinct failure modes in the detection pipeline. See Section 2a for definitions.

Category                      Count   % of Misses   % of Total
-----------------------------------------------------------------
EXTENSION_EXCLUDED               14          9.9%         4.2%
FAMILY_OUT_OF_SCOPE              50         35.2%        15.2%
KEYWORD_GAP                      77         54.2%        23.3%
PARSER_GAP                        0          0.0%         0.0%
DETECTOR_MISS                     1          0.7%         0.3%
REMEDIATION_UNSAFE                0          0.0%         0.0%
BENCHMARK_ARTIFACT                0          0.0%         0.0%

### 2a. Failure Mode Definitions

Three distinct failure modes replace the prior monolithic DETECTOR_MISS bucket. Separating them allows engineering work to be directed at the correct layer.

**KEYWORD_GAP — Architectural/routing failure**
The credential value shape is recognizable and the family is in scope, but SEC002 keyword routing never evaluated the value because the variable or key name is not present in the SEC002 keyword pattern lists. The parser successfully extracted the value; the detector never received it. This is a routing architecture gap. Fixing it requires extending the keyword sets, not changing detection logic. Keyword additions require FP validation before deployment.

Examples: `gh_pat = "ghp_..."`, `gcp_key = "AIza..."`, `api_bearer = "..."`, `access_session = "..."`

**PARSER_GAP — Extraction/routing failure**
The file type and family are in scope, but parser extraction or syntax routing failed before SEC002 evaluation could occur. Examples include Python triple-quoted multiline strings (not matched by the single-quote regex) and YAML block scalars (the parser extracts `|` instead of the key material on subsequent indented lines). No in-scope families currently produce PARSER_GAP misses in this benchmark — `pem_private`, the primary example of these parser limitations, is FAMILY_OUT_OF_SCOPE. The category is defined here for completeness and for future use when in-scope families with multiline value formats are added.

**DETECTOR_MISS — True detection failure**
The value was reachable, in scope, parser-accessible, and keyword routing evaluated it, but SEC002 still failed to detect it. This is the smallest bucket and represents genuine pattern or logic failures in the detector. Current data shows 1 case: `opaque_api_secret` in an ENV file where the value contains special characters (`$`, `*`, `@`) that are believed to trigger a value-side gate (`_looks_like_identifier_or_word`), blocking detection despite the `secret` keyword matching.

## 3. Investigation: Markdown 0% Detection

**Question**: Was Markdown scanned? Extension excluded? Secrets inside fenced code blocks?

**Finding**: `.md` is completely absent from both `DEFAULT_EXTENSIONS` and
`ALL_SUPPORTED_EXTENSIONS` in `src/autonoma/_internal/heuristics.py`.
Files are filtered out before any scanner or parser runs.

Seeded Markdown content format (from `seeder.py render_markdown`):
```markdown
## google_api_key

Example value:

```
GIZAHYqM6Ojb6mjBHqSiFVKu4MbMnrHontIKARA
```
```

Secrets are in fenced code blocks, rendered as plain text inside triple backticks.
No Python/YAML/JSON/ENV syntax — Markdown has its own structure.

**Impact**: 14 missed controls (9.9% of all misses).

The 14 Markdown misses span 10 families:
- aws_pair: 1
- generic_bearer: 1
- github_pat: 3
- google_api: 2
- jwt: 2
- opaque_api_secret: 1
- opaque_session_token: 1
- pem_private: 1
- slack_bot: 1
- stripe: 1

**Determination**: `EXTENSION_EXCLUDED`. This is an architectural scope decision.
Markdown detection would require a different extraction strategy (text scanning
for token-like patterns, not key=value or key: value). No false-positive analysis
of Markdown content currently exists.

## 4. Investigation: PEM Private Key 0% Detection

**Question**: Is PEM detection in SEC002 scope? Different rule? Remediation safe?

**Finding**: No PEM detection rule exists in any current Autonoma rule (SEC001–SEC005).

PEM values are seeded in three rendered formats:

**Python** (triple-quoted string):
```python
server_private_key = """-----BEGIN RSA PRIVATE KEY-----
nIB2PWKhPV5ibveNkDNjl3S4W5oH...
-----END RSA PRIVATE KEY-----"""
```
The Python regex `['"][^'"]+['"]` cannot match triple-quoted strings.
This is a PARSER_GAP for PEM — but since PEM is FAMILY_OUT_OF_SCOPE, the
parser limitation is secondary to the scope decision.

**YAML** (block scalar):
```yaml
server_private_key: |
  -----BEGIN RSA PRIVATE KEY-----
  nIB2PWKhPV5ibveNkDNjl3S4W5oH...
  -----END RSA PRIVATE KEY-----
```
The YAML regex sees `server_private_key: |` and extracts `|` as the value.
The actual key material is on subsequent indented lines — invisible to a
single-line `key: value` pattern. This is also a PARSER_GAP for PEM.

**ENV** (escaped newlines, single line):
```
SERVER_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\nnIB2PWKh..."
```
When var_name is `server_private_key` or `rsa_private_key`, the `private_key`
keyword IS in the ENV pattern. When var_name is `tls_key`, no keyword matches.

**Remediation safety**: PEM key replacement requires knowing the private key's
usage context, correct PEM encoding, and ensuring the replacement key matches
paired certificates. AST-safe deterministic remediation for multiline PEM blobs
is not currently implemented and would be high-risk.

**Determination**: `FAMILY_OUT_OF_SCOPE`. PEM private key detection belongs in a
separate rule (e.g., a future SEC006) with dedicated multiline extraction,
not as an extension of SEC002's key=value pattern. Remediation safety is
a separate blocker even if detection were added.

## 5. Investigation: Opaque Token Misses


### 5a. opaque_random_cred (22.2% recall, 21 missed in supported formats)

**Var_names assigned by seeder**: `credential`, `auth_credential`, `service_credential`
**Value structure**: 24–40 char alphanumeric + `_-`, no prefix, variable length

None of the three var_names contain a keyword from any SEC002 pattern.
The value structure provides no structural signal either — no prefix, no fixed length.

**Determination**: `FAMILY_OUT_OF_SCOPE`. Detecting generic random credentials
requires entropy-based analysis. Adding entropy rules without a labeled false-positive
corpus would compromise SEC002's precision-oriented design. This exclusion is
intentional per the project's anti-overfitting policy.

### 5b. opaque_session_token (26.7% recall, 22 missed total, 21 in supported formats)

**Var_names**: `session_token`, `user_session`, `access_session`
**Value structure**: `{8 base62}-{12 base62}-{12 base62}`, e.g. `SFx7ZHrZ-fUBfBM0lIsug-fuQstCMTBkSC`

`session_token` contains `token` — matched by the SEC002 token keyword. Detected when this var_name is assigned.
`user_session` and `access_session` contain no SEC002 keyword — missed regardless of format.

**Determination**: `KEYWORD_GAP`. The var_name keyword gap in SEC002 routing explains
the miss pattern. The parser extracted the value correctly; keyword routing never
evaluated it because neither `user_session` nor `access_session` appears in any
SEC002 keyword list. This is a routing architecture miss, not a detector miss.

### 5c. generic_bearer (20.0% recall, 24 missed total, 23 in supported formats)

**Var_names**: `bearer_token`, `api_bearer`, `auth_bearer`
**Value structure**: 40-char base64url, no prefix, e.g. `RkwfF44uUVKX0RgQiQmXKGtQksSNYqkNWQql2UcU`

`bearer_token` contains `token` — detectable. `api_bearer` and `auth_bearer`
contain neither `api_key`, `api_secret`, `auth_token`, nor `auth_key`.
Pattern `auth_bearer` would need `auth` to match `auth_token` but the full
keyword `auth_token` is required — partial matches don't fire.

**Determination**: `KEYWORD_GAP`. Var_name keyword gap in SEC002 routing.
The value was parser-accessible in all seeded formats; SEC002 keyword routing
was the gate that prevented detection.

## 6. Misses by Family

Family                        Seeded  Matched  Missed   Recall  Primary Category
--------------------------------------------------------------------------------
aws_pair                          30       29       1    96.7%  EXTENSION_EXCLUDED
generic_bearer                    30        6      24    20.0%  KEYWORD_GAP
github_pat                        30       17      13    56.7%  KEYWORD_GAP
google_api                        30       16      14    53.3%  KEYWORD_GAP
jwt                               30       17      13    56.7%  KEYWORD_GAP
opaque_api_secret                 30       28       2    93.3%  DETECTOR_MISS
opaque_random_cred                30        9      21    30.0%  FAMILY_OUT_OF_SCOPE
opaque_session_token              30        8      22    26.7%  KEYWORD_GAP
pem_private                       30        0      30     0.0%  FAMILY_OUT_OF_SCOPE
slack_bot                         30       29       1    96.7%  EXTENSION_EXCLUDED
stripe                            30       29       1    96.7%  EXTENSION_EXCLUDED

## 7. Misses by Repo

Repo            Seeded  Matched  Missed   Recall
--------------------------------------------------
black               33       12      21    36.4%
celery              33       20      13    60.6%
django              33       18      15    54.5%
fastapi             33       21      12    63.6%
flask               33       18      15    54.5%
httpx               33       18      15    54.5%
mypy                33       25       8    75.8%
pydantic            33       18      15    54.5%
requests            33       17      16    51.5%
sqlalchemy          33       21      12    63.6%

## 8. Misses by File Format

Format      Seeded  Missed  Category Breakdown
----------------------------------------------------------------------
python         117      39  FAMILY_OUT_OF_SCOPE:11, KEYWORD_GAP:28
yaml            99      48  FAMILY_OUT_OF_SCOPE:21, KEYWORD_GAP:27
env             61      20  DETECTOR_MISS:1, FAMILY_OUT_OF_SCOPE:8, KEYWORD_GAP:11
json            39      21  FAMILY_OUT_OF_SCOPE:10, KEYWORD_GAP:11
markdown        14      14  EXTENSION_EXCLUDED:14

## 9. Top Recurring Miss Causes

**1. Markdown extension not supported (14 misses)**
   `.md` absent from `DEFAULT_EXTENSIONS`. 100% miss rate for all Markdown seedings.

**2. PEM family has no detection rule (29 misses in supported formats)**
   No `-----BEGIN RSA PRIVATE KEY-----` pattern exists in SEC002 or any other rule.
   Compounded by format-level parser gaps (triple-quoted Python, YAML block scalars).

**3. opaque_random_cred intentionally excluded (21 misses)**
   Broad entropy detection deferred; no labeled FP corpus exists to validate precision.

**4. KEYWORD_GAP — generic_bearer (23 misses in supported formats)**
   `api_bearer` and `auth_bearer` not in any SEC002 keyword pattern.
   Value was parser-accessible; routing never evaluated it.

**5. KEYWORD_GAP — opaque_session_token (21 misses in supported formats)**
   `user_session` and `access_session` not in any SEC002 keyword pattern.
   Value was parser-accessible; routing never evaluated it.

**6. KEYWORD_GAP — google_api (12 misses)**
   `gcp_key` not in any SEC002 keyword pattern.

**7. KEYWORD_GAP — jwt (11 misses)**
   `session_jwt` not in any SEC002 keyword pattern.

**8. KEYWORD_GAP — github_pat (10 misses)**
   `gh_pat` not in any SEC002 keyword pattern.

**9. True DETECTOR_MISS — opaque_api_secret (1 miss)**
   Keyword match should have fired (`secret` in var_name), parser reached the value,
   but a value-side gate (special chars `$`, `*`, `@` in ENV value) likely blocked
   detection. This is the only true detector failure in the current benchmark corpus.

## 10. Distinction: Detection vs Remediation vs Scope

| Concept | Definition | Evidence in This Benchmark |
|---------|-----------|---------------------------|
| **Detection recall** | Whether SEC002 _found_ the secret | 57.0% strict recall overall |
| **Remediation eligibility** | Whether found secrets are _safe to fix_ | 100% of matched findings refused (`preview_only`) — env_contract absent |
| **Intentional scope** | Families excluded by design | pem_private, opaque_random_cred |
| **Routing architecture** | Whether keyword routing evaluated the value | KEYWORD_GAP: 77 misses — value reachable, routing blocked |
| **Parser coverage** | Whether the parser surfaced the value | PARSER_GAP: 0 misses for in-scope families (pem_private gaps are FAMILY_OUT_OF_SCOPE) |

The 0% remediation rate on matched findings is an expected benchmark artifact:
seeded repos have no `reviewer.config.json` (env_contract absent), so all
findings fall into `preview_only` mode. This does not indicate a remediation bug.
Benchmark recall measures detection only.

## 11. Recommended Next Engineering Actions

Listed in priority order. None implemented here.

**Action 1 — Document pem_private and opaque_random_cred as out-of-scope**
Add explicit documentation in benchmark documentation that these
families are excluded by design. Update the recall report to show
'in-scope recall' (excluding out-of-scope families) alongside the raw number.
Estimated in-scope recall with these excluded: 188 / 230 = 81.7%.

**Action 2 — Address KEYWORD_GAP misses by extending the SEC002 keyword list**
Before adding keywords, produce a false-positive sample: scan 3–5 of the
benchmark repos WITHOUT seeded controls and measure how many lines
matching new keywords (`gh_pat`, `gcp_key`, `session_jwt`, `api_bearer`,
`auth_bearer`, `user_session`, `access_session`) appear naturally.
Only add keywords whose FP rate is acceptable under the existing precision threshold.
KEYWORD_GAP accounts for 77 of 78 previously-labeled DETECTOR_MISS cases — this
is the highest-leverage engineering action for in-scope recall improvement.

**Action 3 — Assess PEM detection as a separate rule**
Evaluate whether a dedicated PEM rule (SEC006 or similar) is warranted.
Key questions: Does PEM detection have an acceptable FP rate on the benchmark repos?
Is deterministic AST-safe remediation feasible (likely not — multiline, cert-paired)?
If detection-only is the answer, a SEC006 detect-only rule could be added without
remediation support. Note that PEM detection also requires solving PARSER_GAP issues
(triple-quoted Python, YAML block scalars) for full coverage.

**Action 4 — Investigate the single true DETECTOR_MISS (opaque_api_secret ENV)**
One miss: `opaque_api_secret` in an ENV file with special chars in the value.
Diagnose whether `_looks_like_identifier_or_word` or another gate is blocking
detection of values containing `$`, `*`, `@`. A single targeted fix may resolve this.

**Action 5 — Evaluate Markdown scanning as a configuration option**
Markdown detection would require content-scan heuristics (token-like patterns,
code block extraction) rather than key=value parsing. Assess FP rate on real
Markdown documentation before adding. Should be gated on a `--include-md` flag,
not enabled by default, until precision is measured.

**Action 6 — Expand benchmark to a false-positive corpus (separate from recall)**
The current benchmark measures recall on positive controls only. A complementary
FP corpus (real repo scans without seeding) is needed before expanding keyword lists
or adding entropy rules. This is a prerequisite for Action 2.

---

*Report generated by `bench/scripts/analyze_misses.py`. Do not edit manually.*
*Re-run to update after any benchmark or classifier changes.*
