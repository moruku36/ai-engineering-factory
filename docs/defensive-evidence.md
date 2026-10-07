# Defensive validation evidence ledger

Experimental / MANUAL_ONLY. This local change makes receipt and candidate JUnit checks share a bounded structural validator. It does not independently establish that a worker ran the reported tests.

| Claim | Test or source | Command | Observed result | Limit |
| --- | --- | --- | --- | --- |
| Old candidate parser accepted four unusable reports | `evidence/junit-baseline.json`; cases in `test_junit_validation.py` | Call `IndependentVerifier.parse_junit_xml` with hidden failure, all-skipped, malformed count and count-only fixtures at the base commit | All four returned true before the change | Synthetic local reproduction; not external exploitation |
| Contradictory counts and all-skipped reports fail closed | `tests/unit/test_junit_validation.py`; `tests/unit/test_handoff.py`; shared `orchestrator/core/junit.py` | `python -m pytest -q tests/unit/test_junit_validation.py tests/unit/test_handoff.py tests/unit/test_artifacts_verifier.py tests/unit/test_approved_container_adapter.py` | 93 passed, 2 skipped, 51 subtests passed during focused validation | Structural consistency, not report authenticity |
| Actual case and outcome counts are used without nested aggregate double counting | Nested suite and failure-without-aggregate regressions in `test_junit_validation.py` | Same focused command | Passed | Supported profile: UTF-8, unnamespaced suite roots, nonnegative ASCII counts up to 10 digits |
| Input is bounded and DTD/entity declarations are refused | Byte boundary, node/depth limit, encoding, malformed hierarchy and DTD regressions | Same focused command | Passed | 10 MiB / 100000 XML elements / depth 64; resource tests lower limits for small fixtures, not load benchmarks |
| Missing collected paths do not bind deletions | `test_missing_collected_path_is_not_deletion_evidence` and `compute_diff` docstring | Same focused command | Missing baseline path yields no changed path; empty diff hash with comparison flag true | Characterization only. Complete repository deletion detection remains unresolved; do not use this flag as proof of a complete diff |
| Existing non-container tests remain passing | `evidence/defensive-local-verification.json` | `python -m pytest -q -rs tests --ignore=tests/integration/test_container_acceptance.py --ignore=tests/integration/test_approved_container_flow.py` | 277 passed, 2 skipped, 51 subtests passed | Two Windows junction fixtures skipped on Linux. Real Docker boundary suites excluded; Windows suite not run |
| Local static and pattern gates pass | Same verification record | `python -m ruff check orchestrator tests scripts`; `python scripts/secret_scan.py` | Both exit 0 | Pattern scan is not a comprehensive secret audit; dependency audit not rerun |

The receipt tool still stops at COLLECTED. Worker success and the legacy string heuristic (including an error-free “ok”) do not constitute independent security acceptance. A forged but internally consistent JUnit report can still pass structural checks; trusted execution and provenance remain separate requirements. Count-only reports formerly accepted by the verifier now fail, so the existing success fixtures include actual test cases.

## Reproduction and revision

Base commit: `4fb014a4ac91fd042b4797c10bd568e5f76880b5`. Implementation and test evidence commit: `2765dc2e3c649b61386fe50193024996c9458f56` (implementation snapshot). This ledger records local validation before publication. No CI had run for these changes at that point; earlier green CI is not evidence for this revision. Subsequent publication and CI results are recorded in the pull request and its checks.

Commands run from the repository root with declared dependencies in an isolated WSL Ubuntu 24.04 Python 3.12 environment. Exact command output, UTC time and SHA-256 hashes of tested Python files are in [the local verification record](../evidence/defensive-local-verification.json). Use `git log -2 --oneline` to identify both local commits. Model/effort selection could not be independently inspected; Astra medium execution is not claimed.
