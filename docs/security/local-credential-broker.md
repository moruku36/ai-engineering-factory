# Local credential use: proposal and offline contract mock

Status: PROPOSAL / OFFLINE MOCK ONLY. Reviewed 2026-10-08.
No Windows screen use, software installation, credential enrollment, OS credential reads,
ACL/network/service changes, provider calls, or billable experiments occurred.
Factory remains EXPERIMENTAL / MANUAL_ONLY.

## Repository decision

Store this reusable execution/security contract in AI Engineering Factory, alongside
its control-plane approval and isolated-execution boundaries. Its README describes
bounded work, command registries, evidence and approval; PROJECT_STATE.md keeps credentials
and live state outside Git. multi-ai-workflow's README describes team roles, routing and
public operational guidance, and explicitly assigns the reusable handoff/evidence layer
to Factory. A later summary/link can be added there after this proposal is accepted.

Sources inspected through the GitHub connector: both README.md files, Factory
AGENTS.md, CONTRIBUTING.md, .agents/rules/RULE-001.yaml and RULE-002.yaml,
.agents/skills/SKILL-001.yaml, PROJECT_STATE.md and ADR-0003. Snapshot tree:
3893f6dc053372e2cc91710ce565ffa6eb8a034b (Factory);
605f60c90c62272f4cd1e47d163944f888ce4e16 (workflow).
This mock is a standalone documentation example; it does not modify task profiles,
command registries, live launcher behavior or ongoing service work.

## Comparison and recommended minimum

| Option | Benefit | Boundary / operating burden | Decision |
|---|---|---|---|
| Windows Credential Manager, generic credential | Native target-based storage; local persistence across this user's logons | CredRead uses current token's logon credential set. Generic API keys are not an application-specific isolation boundary or Credential Guard-protected secret. | Preferred backing store for small Windows deployment, conditional on trust boundary below. |
| DPAPI CurrentUser | Native encryption with integrity protection; noninteractive API | Must implement blob storage, atomic updates, permissions, backup and deletion. Same user can normally decrypt; avoid machine-scope encryption. | Fallback if target-based storage does not fit. |
| Vault | Central policies, audit and leased/dynamic secrets where supported by provider | Server/storage, TLS, unseal/recovery, updates, auth bootstrap and monitoring. Agent auto-auth still needs initial trusted identity. Static provider API keys do not become dynamic/revocable at the provider just by storing in Vault. | Defer unless multiple hosts/users or central governance require it. |
| Local operation broker | Model requests an operation using an opaque reference; only trusted code accesses storage | Additional reviewed code and OS isolation required. A generic secret-get broker merely moves exposure. | Use as the interface over the chosen store, not as an encryption replacement. |

Recommendation: native Credential Manager + a narrowly scoped operation broker and
fixed launcher adapter. No additional paid service or software package is needed for the
native store. This is an architecture recommendation, not an installed runtime.

Microsoft distinguishes CRED_PERSIST_LOCAL_MACHINE (same user's logons on this computer)
from DPAPI CRYPTPROTECT_LOCAL_MACHINE (any user on the computer can decrypt).
Do not confuse these flags. Proposed store: CRED_TYPE_GENERIC,
CRED_PERSIST_LOCAL_MACHINE; no enterprise roaming. DPAPI alternative:
CurrentUser and CRYPTPROTECT_UI_FORBIDDEN, never machine scope.
See [CREDENTIALW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw),
[CredReadW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credreadw),
[DPAPI](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata),
and [Credential Guard limitations](https://learn.microsoft.com/en-us/windows/security/identity-protection/credential-guard/considerations-known-issues).

Vault's production hardening includes TLS, restricted access, audit and secure storage;
dev mode is unsuitable for persistent real secrets. Agent auto-auth/renewal and Windows
service support do not themselves hide secrets from a model-accessible shell.
Official [hardening](https://developer.hashicorp.com/vault/docs/concepts/production-hardening),
[dev mode](https://developer.hashicorp.com/vault/docs/concepts/dev-server),
[Agent](https://developer.hashicorp.com/vault/docs/agent-and-proxy/agent).
If later needed, use only the [official distribution](https://developer.hashicorp.com/vault/docs/get-vault),
verify its published checksum/signature, and review current
[license terms](https://www.hashicorp.com/en/license-faq) before installation.
Self-hosted software does not eliminate operating/storage costs; hosted/enterprise costs
require a current quote and approval. No cost estimate or subscription change is authorized here.

## Threat model and interface

At-rest encryption reduces accidental exposure and offline disclosure. It cannot promise
secrecy from arbitrary code running as the storing user, administrators, malware or memory
inspection. An AI with unrestricted shell execution as that same user could bypass a
broker and call CredRead/DPAPI directly. To enforce the requested model boundary, workers
must lack that identity's store, process memory and writable executable/policy paths.
Use a separately protected execution principal or an OS sandbox with demonstrable denial;
the Windows runtime is not already verified by Factory's Linux container checks.

Flow: worker -> authenticated local IPC -> trusted broker -> fixed adapter -> service.
Only broker/adapter sees credential bytes; worker receives fixed status fields.
Do not inject credentials into model-owned child processes, argv, inherited environment,
temporary files, prompts, stdout/stderr or transcripts. The fixed adapter should perform
the authenticated request itself. If a launcher must receive a key, it must be a trusted,
isolated process with narrowly inherited private IPC handles, controlled descendants and
no secret-bearing output; argv/env delivery is not the default.

Production request contains only an opaque handle and a registered operation ID.
No arbitrary URL, executable, arguments, credential target or retrieval command.
Broker maps operation to fixed endpoint/method/output schema, checks authenticated caller,
task/run and policy digest, expiry and revocation, consumes the bounded grant atomically
before execution, and emits an allowlisted response. Do not relay provider response bodies,
headers, exceptions or child output: these can echo keys, account or device information.
Audit only generic operation/outcome and safe correlation IDs, never credential values,
handle capabilities, raw payloads, hostnames or account identifiers.

Authenticated identity must come from OS transport, never caller-supplied JSON.
Named pipes need an explicit narrow security descriptor: Windows default permissions
include broader readers. Reject remote clients; verify both server and client identity,
limit message sizes and concurrency. Socket loopback alone is not authorization.
See [Microsoft named-pipe access rights](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-security-and-access-rights).
Executable signing/hash checks supplement but do not replace an OS principal boundary.
Production randomness, transactional replay protection, crash/ambiguous-outcome handling,
rate limits, secret buffer lifetime and transport are still unimplemented.
Credential enrollment approval is separate from authorization for each operation;
pod creation/start/delete and any charge require their own human-authorized policy.

## One-time enrollment, rotation and deletion (not implemented)

After concrete owner approval, a local trusted enrollment utility accepts each existing
service credential directly in hidden input (never in chat/model tools or command history)
and writes it once to a broker-owned store outside the repository. A one-time input is
still needed; routine requests should then avoid both key entry and screen occupation.
No keys are created here. Enroll only the services explicitly approved; independently
approve persistence of any currently process-only tunnel credential.

Approval record must specify service/credential scope, target identity, persistence,
allowed operations/endpoints, launcher/adapter executable and policy version, worker
isolation, ACL/service/network changes, enrollment method, expiry/rotation and deletion.
Do not include real SID, machine names, destinations or credential target names in public Git.
Decide whether broker lifetime is per-session or persistent; no background service now.

Rotation: revoke outstanding handles, pause new requests, replace the stored key through
trusted enrollment, verify with a separately authorized nonbillable operation, then revoke
the old key at the provider. Do not automatically retry uncertain external mutations.
Removal: disable grants and stop/clear trusted processes first, delete the local target
using [CredDeleteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-creddeletew)
(or DPAPI blob and approved backups), then revoke the provider credential.
Local deletion alone does not revoke provider access, active sessions or copied keys.
Revoking a handle cannot undo an already-running action; cancellation needs a separate
provider-specific design. Secure erasure of memory/disk cannot be guaranteed by this mock.

## Deliverables and verification

The adjacent broker-mock.mjs and broker-mock.test.mjs form a standalone, dependency-free
contract example. No storage, secret input, actual launcher, networking, subprocess or
persistent state exists. The trusted test harness can issue/revoke in-memory test handles;
these functions must never be worker tools. Predictable mock handles and supplied
mock identity/clock are intentionally nonproduction. Output has only a status field.

16 contract checks passed in the tools' JavaScript V8 isolate after removing only module
import/export declarations to evaluate these same sources. Checks cover allowed execution,
replay, expiry, revocation, caller/task mismatch, billable and secret-read operations,
URL/argv injection, unknown handles, invalid clock, null input, denial preserving a grant,
output fields, and absence of retrieval/launcher APIs. This is not Node, Windows IPC,
credential-store, service, provider, isolation, independent-review or repository CI evidence.
Local shell setup failed once; it was not retried and no native tests were claimed.
For an approved test environment, the standalone check is:
node docs/examples/local-credential-broker/broker-mock.test.mjs
Use the project's registered-command policy for any future agent execution.

Remaining gates: human architecture review; real backend/transport and authenticated
isolation implementation; Windows denial/leak/crash/concurrency tests; repository CI;
then concrete owner approval for enrollment/persistence and any security setting changes.
No install is currently needed; official Vault installation remains a conditional plan.
