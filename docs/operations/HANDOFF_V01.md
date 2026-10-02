# Local artifact handoff v0.1

This is the first bounded foundation for the approved personal AI team plan:
an offline manifest contract and receiver byte checks. Factory remains
Experimental / MANUAL_ONLY. No native agent adapter, network retrieval, execution
service, model selection, cloud access, or new persistent storage is added.

## Workflow

1. Before a run, fix the required inventory, request/input pins, acceptance criteria,
   source snapshot, allowed operations and limits. After production, record exact
   output sizes, SHA-256 and persistent storage IDs/versions. Preserve previous
   attempts. A changed input/output needs a new attempt and affected tests/review.
2. Store `manifest.json` and allowlisted outputs in an existing approved private
   location. Keep raw logs and secrets outside the shared packet. Keep the manifest
   SHA-256, run ID, attempt ID and output versions in the coordinator's **separate
   trusted record**. The packet cannot supply its own trusted digest. Freeze the
   manifest bytes, including encoding/newlines, before computing the digest.
3. Retrieve the packet bytes into a quiescent directory in the receiver environment
   using existing supported tools. Do not treat a sender path or URL as retrieval.
4. Run the local receipt command with the coordinator record already obtained
   through a trusted route:

   ```powershell
   python -m orchestrator.handoff --packet C:\private\receiver\packet `
     --trust C:\private\coordinator\trusted.json `
     --receipt C:\private\receiver\receipt-attempt-1.json
   ```

   Exit 0 means **COLLECTED only**. Exit 2 means the receipt check is blocked; no
   success receipt is written. Receipt JSON is completely UTF-8 encoded before
   file creation, then flushed in a same-directory temporary file and atomically
   published by a non-overwriting hard link. Existing receipt files are never
   overwritten, including concurrent creation. Filesystems without hard-link
   support fail closed. A hard process kill may leave a temporary file, but does
   not publish partially written final evidence. Temporary cleanup is best effort:
   a cleanup error may retain a scratch file,
   without changing publication success or masking the original publication error.
   The trust and receipt files must be outside the packet. Authentication of the
   coordinator record belongs to the existing trusted delivery route, not this
   local utility. The API caller has the same trust responsibility.
5. Independently execute acceptance tests against the pinned candidate and obtain
   any required independent review. Then reconcile actual execution/cancellation
   and receiver handoff separately. This utility never grants VERIFIED or COMPLETE,
   and never retries or dispatches jobs. Its receipt retains `declared_status` as
   a sender assertion, plus an explicit unknown verification and the next step.

## Contract

The runnable anonymous example is in
[`../examples/handoff-v01`](../examples/handoff-v01/manifest.json).
It is a **synthetic fixture**, including its JUnit, not a live business or RunPod run.
Its companion `trusted.example.json` belongs outside the received packet and must
be independently pinned in real work. It is instructional, not authenticated.

- `schema_version`: exactly `0.1`; run/attempt IDs and optional parent, purpose,
  producer, request SHA-256, acceptance criteria, next step, declared status.
- `source`: repository, full 40-character Git SHA or `unknown`, fixed snapshot
  SHA-256, dirty flag, full base SHA or `unknown`, complete-diff requirement.
  The snapshot hash must cover the candidate used by tests/review; the utility
  validates the binding but does not create or reconstruct the source snapshot.
- `inputs`: ID, byte count, SHA-256. These are frozen provenance pins, not claims
  that the input bytes were reacquired by this output-receipt operation.
- `environment`: execution kind, OS, tool versions, separate requested and observed
  model/effort. Use `unknown` when identity is not observable. Model names do not
  imply permission or runtime capability.
- `execution`: accepted/started/ended timestamps and exit code, `null` if unknown.
  It records observations supplied by the caller; this tool does not execute or
  authenticate those observations.
- `outputs`: exact portable relative path, purpose, required flag, size, SHA-256,
  producer, retrieval timestamp, persistent storage ID and string version.
- `tests`: explicit required flag. Required JUnit must be a required inventory
  entry; command/tool version and target snapshot hash must be recorded. Missing,
  incomplete, zero-case, all-skipped, failed, inconsistent-count and DTD/entity
  reports are rejected. JUnit accepts UTF-8 (optional UTF-8 BOM) only; NUL bytes,
  other declared encodings, DTD and entity declarations are rejected before XML
  parsing. A matching report remains collected evidence; fabricated
  reports cannot prove actual execution through this utility alone.
- `reviews`: reviewer, target snapshot hash, verdict and findings; `[]` if no
  review was obtained. Receipt does not promote review assertions to approval.
- `limits_and_authority`: caller record of permitted operations, deadlines,
  attempt/budget limits. Never include secret values. This tool grants no authority.

The separate trust JSON has `manifest_sha256`, `run_id`, `attempt_id` and
`output_versions` (exact path → pinned version for every inventory entry).
Optional missing files are listed in the receipt. Extra packet files are not read,
copied or counted as received. Required outputs cannot silently become optional:
changing the manifest invalidates the external pin.

Bounds: 1 MiB manifest/trust, 100 output entries, 10 MiB per file, 50 MiB declared
total. Portable paths reject traversal, drive/ADS syntax, reserved Windows names,
control/credential paths and case-insensitive duplicate or conflicting entries.
Files and directory components must not be symlinks or Windows reparse points.
The Windows check uses `lstat().st_file_attributes`, available in Python 3.11;
it does not rely on Python 3.12's `Path.is_junction`. Runtime tests were performed
on Windows Python 3.12, including a real junction and simulated older pathlib.
This is
an offline check of a receiver-owned, stable directory; concurrent hostile mutation
is outside its threat model. It is not a sandbox or a secret-safety guarantee.

## CPU verification and remaining gates

With Python >=3.11 and no third-party dependencies:

```powershell
python -m unittest discover -s tests/unit -p test_handoff.py -v
```

The same unittest cases participate in the normal pytest suite. Negative fixtures
cover missing/truncated/tampered output, packet replacement, run/attempt/version
mix-ups, missing/invalid JUnit, unsafe paths/links, changed review/test targets,
unknown base, and false promotion of sender states. No live agent or GPU is used.

The existing container adapter's extraction default, deletion/mode diff omission,
and best-effort unknown-base path are **not repaired by this milestone**. This
receipt tool refuses complete-diff tasks, including known-base cases, rather than
certifying a partial diff. Those paths require separate reproducible negative
tests and a subsequent approved repair before reuse. Process cancellation/crash
reconciliation also remains with the existing controller; no process state is
inferred from a packet assertion.

Use only synthetic email and anonymous technical fixtures for the first local
handoff. Human acceptance must check unanswered questions, contradictions and
unauthorized commitments; hashes cannot check communication quality. RunPod
requires its existing authorized fixed selftest and actual outcome evidence; this
utility does not provide that execution capability. Three comparable real-work
handoffs and the plan's timing measurements remain future adoption gates.
