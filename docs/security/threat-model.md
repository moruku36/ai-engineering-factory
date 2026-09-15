# Threat Model & Security Boundaries

## 1. Threat Vectors
1. **Malicious or Hallucinated Task Manifests**: Manifests attempting path traversal (`../`, absolute paths, symlink attacks) or command injection via shell metacharacters.
2. **Untrusted Agent Output**: Workers attempting to overwrite system files, exfiltrate environment secrets, or tamper with Git metadata (`.git`).
3. **Approval Forgery**: Counterfeit approval tokens or tokens reused across tasks or expired tokens.
4. **Race Conditions / Concurrent Writers**: Simultaneous writes causing split-brain state or corrupted ledgers.

## 2. Mitigation Strategy
- **Strict Parsing**: Safe YAML parsing only, JSON Schema 2020-12 validation, size limit 1 MiB, max recursion depth 20.
- **Typed Command Execution**: Disallow `shell=True`. Commands mapped to explicit, pre-approved command registries.
- **Single Writer Pattern**: Lock acquisition and revision verification prior to any state update.
- **Token Binding**: Approval tokens cryptographically bound to SHA of task spec, policy, target ref, and argv.
