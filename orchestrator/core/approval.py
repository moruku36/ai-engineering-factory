"""Approval token management, HMAC verification, and cross-process atomic consumption engine."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.core.auth import (
    ApproverRegistry,
    compute_operator_signature,
)
from orchestrator.core.schema import validate_against_schema


class ApprovalVerificationError(Exception):
    """Raised when an approval token fails validation, is tampered with, or expired."""


class ApprovalReplayError(ApprovalVerificationError):
    """Raised when an approval token is reused (replay attack)."""


class ApprovalExpiredError(ApprovalVerificationError):
    """Raised when an approval token has expired."""


class ApprovalRevokedError(ApprovalVerificationError):
    """Raised when an approval token has been revoked."""


def _compute_token_signature(token_data: dict[str, Any], secret_key: bytes) -> str:
    """Compute HMAC-SHA256 signature across all critical token fields."""
    signed_fields = [
        "token_id", "action", "repository", "task_id", "head_sha", "target_ref",
        "argv_digest", "policy_hash", "plan_hash", "approved_by", "created_at", "expires_at",
    ]
    if "key_id" in token_data:
        signed_fields.append("key_id")
    if "operator_signature" in token_data:
        signed_fields.append("operator_signature")

    canonical = json.dumps(
        {name: token_data[name] for name in signed_fields}, sort_keys=True, separators=(",", ":")
    )
    return hmac.new(secret_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


class ApprovalManager:
    """Issues and atomically verifies/consumes approval tokens bound to execution context."""

    def __init__(
        self,
        approvals_dir: Path | str | None = None,
        registry: ApproverRegistry | None = None,
        enforce_authentication: bool = False,
    ):
        self._secret_key = os.environ.get("AI_FACTORY_APPROVAL_SECRET", "").encode("utf-8")
        if len(self._secret_key) < 32:
            raise ApprovalVerificationError("A provisioned control-plane signing key is required (minimum 32 bytes)")
        if approvals_dir is None:
            self.approvals_dir = Path(__file__).resolve().parent.parent.parent / "state" / "approvals"
        else:
            self.approvals_dir = Path(approvals_dir)
        self.approvals_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.approvals_dir / "approvals.sqlite"
        self.registry = registry or ApproverRegistry()
        self.enforce_authentication = enforce_authentication or self.registry.is_configured
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    token_id TEXT PRIMARY KEY,
                    signature TEXT NOT NULL,
                    action TEXT NOT NULL,
                    repository TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    head_sha TEXT NOT NULL,
                    target_ref TEXT NOT NULL,
                    argv_digest TEXT NOT NULL,
                    policy_hash TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    approved_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed INTEGER NOT NULL DEFAULT 0,
                    consumed_at TEXT,
                    key_id TEXT,
                    operator_signature TEXT,
                    revoked INTEGER NOT NULL DEFAULT 0,
                    revoked_at TEXT,
                    revocation_reason TEXT
                );
                """
            )
            # Ensure columns exist in case table was created previously without them
            cursor = conn.execute("PRAGMA table_info(approvals);")
            existing_cols = {row[1] for row in cursor.fetchall()}
            for col, col_type in (
                ("key_id", "TEXT"),
                ("operator_signature", "TEXT"),
                ("revoked", "INTEGER NOT NULL DEFAULT 0"),
                ("revoked_at", "TEXT"),
                ("revocation_reason", "TEXT"),
            ):
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE approvals ADD COLUMN {col} {col_type};")

    def _get_token_path(self, token_id: str) -> Path:
        return self.approvals_dir / f"{token_id}.json"

    def issue_token(
        self,
        action: str,
        repository: str,
        task_id: str,
        head_sha: str,
        target_ref: str,
        argv_digest: str,
        policy_hash: str,
        plan_hash: str,
        approved_by: str,
        expires_at: str,
    ) -> dict[str, Any]:
        """Issue a new one-time approval token bound to context."""
        token_id = f"tok-{secrets.token_hex(16)}"
        created_at = datetime.now(UTC).isoformat()

        token_data: dict[str, Any] = {
            "token_id": token_id,
            "action": action,
            "repository": repository,
            "task_id": task_id,
            "head_sha": head_sha,
            "target_ref": target_ref,
            "argv_digest": argv_digest,
            "policy_hash": policy_hash,
            "plan_hash": plan_hash,
            "approved_by": approved_by,
            "created_at": created_at,
            "expires_at": expires_at,
            "consumed": False,
        }

        validate_against_schema(token_data, "approval.schema.json")
        signature = _compute_token_signature(token_data, self._secret_key)

        # Store in SQLite transactional ledger
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO approvals (
                    token_id, signature, action, repository, task_id,
                    head_sha, target_ref, argv_digest, policy_hash, plan_hash,
                    approved_by, created_at, expires_at, consumed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0);
                """,
                (
                    token_id,
                    signature,
                    action,
                    repository,
                    task_id,
                    head_sha,
                    target_ref,
                    argv_digest,
                    policy_hash,
                    plan_hash,
                    approved_by,
                    created_at,
                    expires_at,
                ),
            )
            conn.execute("COMMIT;")

        # Also write backward-compatible JSON file for audit trail
        token_path = self._get_token_path(token_id)
        temp_path = token_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)
        os.replace(temp_path, token_path)

        return token_data

    def issue_authenticated_token(
        self,
        action: str,
        repository: str,
        task_id: str,
        head_sha: str,
        target_ref: str,
        argv_digest: str,
        policy_hash: str,
        plan_hash: str,
        approved_by: str,
        operator_key: bytes | str,
        expires_at: str,
    ) -> dict[str, Any]:
        """Issue a verified human-authenticated token cryptographically signed by approver."""
        if not self.registry.is_configured:
            raise ApprovalVerificationError("Approver authentication infrastructure is not configured (BLOCKED)")

        key_id = self.registry.authenticate_and_authorize(approved_by, operator_key, action)
        token_id = f"tok-{secrets.token_hex(16)}"
        created_at = datetime.now(UTC).isoformat()

        token_data: dict[str, Any] = {
            "token_id": token_id,
            "action": action,
            "repository": repository,
            "task_id": task_id,
            "head_sha": head_sha,
            "target_ref": target_ref,
            "argv_digest": argv_digest,
            "policy_hash": policy_hash,
            "plan_hash": plan_hash,
            "approved_by": approved_by,
            "created_at": created_at,
            "expires_at": expires_at,
            "consumed": False,
            "key_id": key_id,
        }

        operator_signature = compute_operator_signature(token_data, operator_key)
        token_data["operator_signature"] = operator_signature

        validate_against_schema(token_data, "approval.schema.json")
        signature = _compute_token_signature(token_data, self._secret_key)

        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            conn.execute(
                """
                INSERT INTO approvals (
                    token_id, signature, action, repository, task_id,
                    head_sha, target_ref, argv_digest, policy_hash, plan_hash,
                    approved_by, created_at, expires_at, consumed,
                    key_id, operator_signature, revoked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0);
                """,
                (
                    token_id,
                    signature,
                    action,
                    repository,
                    task_id,
                    head_sha,
                    target_ref,
                    argv_digest,
                    policy_hash,
                    plan_hash,
                    approved_by,
                    created_at,
                    expires_at,
                    key_id,
                    operator_signature,
                ),
            )
            conn.execute("COMMIT;")

        token_path = self._get_token_path(token_id)
        temp_path = token_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)
        os.replace(temp_path, token_path)

        return token_data

    def revoke_token(self, token_id: str, reason: str = "") -> None:
        """Revoke an approval token, preventing any future consumption."""
        now_iso = datetime.now(UTC).isoformat()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute("SELECT consumed, revoked FROM approvals WHERE token_id = ?;", (token_id,))
            row = cursor.fetchone()
            if not row:
                conn.execute("ROLLBACK;")
                raise ApprovalVerificationError(f"Approval token '{token_id}' not found")
            consumed, _revoked = row
            if consumed:
                conn.execute("ROLLBACK;")
                raise ApprovalVerificationError(f"Cannot revoke already consumed token '{token_id}'")
            conn.execute(
                "UPDATE approvals SET revoked = 1, revoked_at = ?, revocation_reason = ? WHERE token_id = ?;",
                (now_iso, reason, token_id),
            )
            conn.execute("COMMIT;")

        token_path = self._get_token_path(token_id)
        if token_path.exists():
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["revoked"] = True
                data["revocation_reason"] = reason
                temp_path = token_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_path, token_path)
            except OSError:
                pass

    def verify_and_consume_token(
        self,
        token_id: str,
        action: str,
        repository: str,
        task_id: str,
        head_sha: str,
        target_ref: str,
        argv_digest: str,
        policy_hash: str,
        plan_hash: str,
    ) -> None:
        """Verify all bound attributes, signature, expiry, and consume atomically across processes."""
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE;")
            cursor = conn.execute(
                "SELECT token_id, signature, action, repository, task_id, head_sha, target_ref, "
                "argv_digest, policy_hash, plan_hash, approved_by, created_at, expires_at, consumed, "
                "key_id, operator_signature, revoked "
                "FROM approvals WHERE token_id = ?;",
                (token_id,),
            )
            row = cursor.fetchone()
            if not row:
                conn.execute("ROLLBACK;")
                raise ApprovalVerificationError(f"Approval token '{token_id}' not found or forged")

            (
                t_id,
                t_sig,
                t_action,
                t_repo,
                t_task,
                t_head,
                t_target,
                t_argv,
                t_pol,
                t_plan,
                t_app_by,
                t_created,
                t_expires,
                t_consumed,
                t_key_id,
                t_op_sig,
                t_revoked,
            ) = row

            if t_revoked:
                conn.execute("ROLLBACK;")
                raise ApprovalRevokedError(f"Approval token '{token_id}' has been revoked")

            if t_consumed:
                conn.execute("ROLLBACK;")
                raise ApprovalReplayError(f"Approval token '{token_id}' has already been consumed")

            # Expiry check
            now = datetime.now(UTC)
            exp = datetime.fromisoformat(t_expires)
            if now > exp:
                conn.execute("ROLLBACK;")
                raise ApprovalExpiredError(f"Approval token '{token_id}' expired at {t_expires}")

            # Enforce approver authentication when configured or requested
            if self.enforce_authentication:
                if not t_key_id or not t_op_sig:
                    conn.execute("ROLLBACK;")
                    raise ApprovalVerificationError(
                        f"Unauthenticated legacy approval token '{token_id}' rejected: re-issuance required"
                    )
                self.registry.verify_token_identity(t_app_by, t_key_id, action)

            # Verify cryptographic HMAC signature
            token_dict = {
                "token_id": t_id,
                "action": t_action,
                "repository": t_repo,
                "task_id": t_task,
                "head_sha": t_head,
                "target_ref": t_target,
                "argv_digest": t_argv,
                "policy_hash": t_pol,
                "plan_hash": t_plan,
                "approved_by": t_app_by,
                "created_at": t_created,
                "expires_at": t_expires,
            }
            if t_key_id:
                token_dict["key_id"] = t_key_id
            if t_op_sig:
                token_dict["operator_signature"] = t_op_sig

            expected_sig = _compute_token_signature(token_dict, self._secret_key)
            if not hmac.compare_digest(t_sig, expected_sig):
                conn.execute("ROLLBACK;")
                raise ApprovalVerificationError(f"Cryptographic signature mismatch on token '{token_id}'")

            # Attribute binding checks
            bindings = {
                "action": (t_action, action),
                "repository": (t_repo, repository),
                "task_id": (t_task, task_id),
                "head_sha": (t_head, head_sha),
                "target_ref": (t_target, target_ref),
                "argv_digest": (t_argv, argv_digest),
                "policy_hash": (t_pol, policy_hash),
                "plan_hash": (t_plan, plan_hash),
            }

            for attr, (actual, expected) in bindings.items():
                if actual != expected:
                    conn.execute("ROLLBACK;")
                    raise ApprovalVerificationError(
                        f"Token binding mismatch on '{attr}': expected '{expected}', found in token '{actual}'"
                    )

            # Atomically mark consumed
            now_iso = datetime.now(UTC).isoformat()
            cursor = conn.execute(
                "UPDATE approvals SET consumed = 1, consumed_at = ? WHERE token_id = ? AND consumed = 0;",
                (now_iso, token_id),
            )
            if cursor.rowcount == 0:
                conn.execute("ROLLBACK;")
                raise ApprovalReplayError(f"Approval token '{token_id}' was consumed concurrently")

            conn.execute("COMMIT;")

        # Update JSON file to reflect consumption
        token_path = self._get_token_path(token_id)
        if token_path.exists():
            try:
                with open(token_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                data["consumed"] = True
                temp_path = token_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_path, token_path)
            except OSError:
                pass


def compute_argv_digest(argv: list[str]) -> str:
    """Compute SHA256 digest of command argv array."""
    serialized = json.dumps(argv, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
