"""Approval token management, HMAC verification, and cross-process atomic consumption engine."""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.core.auth import (
    ApproverRegistry,
    compute_operator_signature,
)
from orchestrator.core.schema import validate_against_schema
from orchestrator.core.sqlite_util import connect_wal


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
        return connect_wal(self.db_path)

    def _init_db(self) -> None:
        with closing(self._get_connection()) as conn:
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

    def _write_token_json(self, token_data: dict[str, Any]) -> None:
        """Write the backward-compatible JSON audit file for a token, atomically."""
        token_path = self._get_token_path(token_data["token_id"])
        temp_path = token_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)
        os.replace(temp_path, token_path)

    def _update_token_json(self, token_id: str, updates: dict[str, Any]) -> None:
        """Best-effort mirror of a DB-side token mutation into the JSON audit file.

        The database row is the source of truth (already committed by the caller);
        this is a convenience copy for tools that read the JSON file directly, so a
        missing or malformed file here is not itself an error.
        """
        token_path = self._get_token_path(token_id)
        if not token_path.exists():
            return
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            data.update(updates)
            temp_path = token_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, token_path)
        except (OSError, json.JSONDecodeError, KeyError):
            pass

    def _persist_new_token(self, token_data: dict[str, Any]) -> dict[str, Any]:
        """Validate, sign, and durably store a freshly-built token (DB row + JSON audit file)."""
        validate_against_schema(token_data, "approval.schema.json")
        signature = _compute_token_signature(token_data, self._secret_key)

        with closing(self._get_connection()) as conn:
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
                    token_data["token_id"],
                    signature,
                    token_data["action"],
                    token_data["repository"],
                    token_data["task_id"],
                    token_data["head_sha"],
                    token_data["target_ref"],
                    token_data["argv_digest"],
                    token_data["policy_hash"],
                    token_data["plan_hash"],
                    token_data["approved_by"],
                    token_data["created_at"],
                    token_data["expires_at"],
                    token_data.get("key_id"),
                    token_data.get("operator_signature"),
                ),
            )
            conn.execute("COMMIT;")

        self._write_token_json(token_data)
        return token_data

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
        token_data: dict[str, Any] = {
            "token_id": f"tok-{secrets.token_hex(16)}",
            "action": action,
            "repository": repository,
            "task_id": task_id,
            "head_sha": head_sha,
            "target_ref": target_ref,
            "argv_digest": argv_digest,
            "policy_hash": policy_hash,
            "plan_hash": plan_hash,
            "approved_by": approved_by,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": expires_at,
            "consumed": False,
        }
        return self._persist_new_token(token_data)

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

        token_data: dict[str, Any] = {
            "token_id": f"tok-{secrets.token_hex(16)}",
            "action": action,
            "repository": repository,
            "task_id": task_id,
            "head_sha": head_sha,
            "target_ref": target_ref,
            "argv_digest": argv_digest,
            "policy_hash": policy_hash,
            "plan_hash": plan_hash,
            "approved_by": approved_by,
            "created_at": datetime.now(UTC).isoformat(),
            "expires_at": expires_at,
            "consumed": False,
            "key_id": key_id,
        }
        token_data["operator_signature"] = compute_operator_signature(token_data, operator_key)
        return self._persist_new_token(token_data)

    def revoke_token(self, token_id: str, reason: str = "") -> None:
        """Revoke an approval token, preventing any future consumption."""
        now_iso = datetime.now(UTC).isoformat()
        with closing(self._get_connection()) as conn:
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

        self._update_token_json(token_id, {"revoked": True, "revocation_reason": reason})

    _TOKEN_ROW_FIELDS = (
        "token_id", "signature", "action", "repository", "task_id", "head_sha", "target_ref",
        "argv_digest", "policy_hash", "plan_hash", "approved_by", "created_at", "expires_at",
        "consumed", "key_id", "operator_signature", "revoked",
    )

    def _fetch_token_fields(self, conn: sqlite3.Connection, token_id: str) -> dict[str, Any] | None:
        """Fetch a token's raw DB row as a field-name-keyed dict, or None if it doesn't exist."""
        cursor = conn.execute(
            f"SELECT {', '.join(self._TOKEN_ROW_FIELDS)} FROM approvals WHERE token_id = ?;",
            (token_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(zip(self._TOKEN_ROW_FIELDS, row))

    @staticmethod
    def _check_not_revoked(fields: dict[str, Any], token_id: str) -> None:
        if fields["revoked"]:
            raise ApprovalRevokedError(f"Approval token '{token_id}' has been revoked")

    @staticmethod
    def _check_not_expired(fields: dict[str, Any], token_id: str) -> None:
        t_expires = fields["expires_at"]
        now = datetime.now(UTC)
        try:
            exp = datetime.fromisoformat(t_expires)
            if exp.tzinfo is None:
                raise ApprovalVerificationError(
                    f"Approval token '{token_id}' expires_at lacks timezone: {t_expires}"
                )
        except (ValueError, TypeError) as exc:
            raise ApprovalVerificationError(
                f"Approval token '{token_id}' has invalid expires_at: {t_expires}"
            ) from exc
        if now > exp:
            raise ApprovalExpiredError(f"Approval token '{token_id}' expired at {t_expires}")

    def _check_authentication(self, fields: dict[str, Any], token_id: str, action: str) -> None:
        if not self.enforce_authentication:
            return
        if not fields["key_id"] or not fields["operator_signature"]:
            raise ApprovalVerificationError(
                f"Unauthenticated legacy approval token '{token_id}' rejected: re-issuance required"
            )
        self.registry.verify_token_identity(fields["approved_by"], fields["key_id"], action)

    def _verify_signature_and_bindings(
        self,
        fields: dict[str, Any],
        token_id: str,
        action: str,
        repository: str,
        task_id: str,
        head_sha: str,
        target_ref: str,
        argv_digest: str | None,
        policy_hash: str | None,
        plan_hash: str | None,
        *,
        require_all_bindings: bool,
    ) -> dict[str, Any]:
        """Recompute the HMAC signature and check every attribute the token is bound to.

        require_all_bindings=True (consumption) requires argv_digest/policy_hash/plan_hash
        to match exactly; =False (post-hoc binding checks) only checks those the caller
        actually supplied, since a caller may not have all three available.
        """
        token_dict = {
            "token_id": fields["token_id"],
            "action": fields["action"],
            "repository": fields["repository"],
            "task_id": fields["task_id"],
            "head_sha": fields["head_sha"],
            "target_ref": fields["target_ref"],
            "argv_digest": fields["argv_digest"],
            "policy_hash": fields["policy_hash"],
            "plan_hash": fields["plan_hash"],
            "approved_by": fields["approved_by"],
            "created_at": fields["created_at"],
            "expires_at": fields["expires_at"],
        }
        if fields["key_id"]:
            token_dict["key_id"] = fields["key_id"]
        if fields["operator_signature"]:
            token_dict["operator_signature"] = fields["operator_signature"]

        expected_sig = _compute_token_signature(token_dict, self._secret_key)
        if not hmac.compare_digest(fields["signature"], expected_sig):
            raise ApprovalVerificationError(f"Cryptographic signature mismatch on token '{token_id}'")

        bindings = {
            "action": (fields["action"], action),
            "repository": (fields["repository"], repository),
            "task_id": (fields["task_id"], task_id),
            "head_sha": (fields["head_sha"], head_sha),
            "target_ref": (fields["target_ref"], target_ref),
        }
        if require_all_bindings or argv_digest is not None:
            bindings["argv_digest"] = (fields["argv_digest"], argv_digest)
        if require_all_bindings or policy_hash is not None:
            bindings["policy_hash"] = (fields["policy_hash"], policy_hash)
        if require_all_bindings or plan_hash is not None:
            bindings["plan_hash"] = (fields["plan_hash"], plan_hash)

        for field_name, (token_val, expected_val) in bindings.items():
            if token_val != expected_val:
                raise ApprovalVerificationError(
                    f"Token binding mismatch on '{field_name}': expected '{expected_val}', found '{token_val}'"
                )

        return token_dict

    def get_token(self, token_id: str) -> dict[str, Any] | None:
        """Query token record by token_id from approvals database."""
        with closing(self._get_connection()) as conn:
            fields = self._fetch_token_fields(conn, token_id)
            if fields is None:
                return None
            return {**fields, "consumed": bool(fields["consumed"]), "revoked": bool(fields["revoked"])}

    def verify_consumed_token_binding(
        self,
        token_id: str,
        action: str,
        repository: str,
        task_id: str,
        head_sha: str,
        target_ref: str,
        argv_digest: str | None = None,
        policy_hash: str | None = None,
        plan_hash: str | None = None,
    ) -> dict[str, Any]:
        """Cryptographically verify all bindings of an already-consumed approval token without double-consuming."""
        with closing(self._get_connection()) as conn:
            fields = self._fetch_token_fields(conn, token_id)
            if fields is None:
                raise ApprovalVerificationError(f"Approval token '{token_id}' not found or forged")

            self._check_not_revoked(fields, token_id)
            if not fields["consumed"]:
                raise ApprovalVerificationError(f"Approval token '{token_id}' has not been consumed yet")
            self._check_authentication(fields, token_id, action)
            token_dict = self._verify_signature_and_bindings(
                fields, token_id, action, repository, task_id, head_sha, target_ref,
                argv_digest, policy_hash, plan_hash, require_all_bindings=False,
            )
            token_dict["consumed"] = True
            token_dict["revoked"] = False
            return token_dict

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
        with closing(self._get_connection()) as conn:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                fields = self._fetch_token_fields(conn, token_id)
                if fields is None:
                    raise ApprovalVerificationError(f"Approval token '{token_id}' not found or forged")

                self._check_not_revoked(fields, token_id)
                if fields["consumed"]:
                    raise ApprovalReplayError(f"Approval token '{token_id}' has already been consumed")
                self._check_not_expired(fields, token_id)
                self._check_authentication(fields, token_id, action)
                self._verify_signature_and_bindings(
                    fields, token_id, action, repository, task_id, head_sha, target_ref,
                    argv_digest, policy_hash, plan_hash, require_all_bindings=True,
                )

                now_iso = datetime.now(UTC).isoformat()
                cursor = conn.execute(
                    "UPDATE approvals SET consumed = 1, consumed_at = ? WHERE token_id = ? AND consumed = 0;",
                    (now_iso, token_id),
                )
                if cursor.rowcount == 0:
                    raise ApprovalReplayError(f"Approval token '{token_id}' was consumed concurrently")
            except Exception:
                conn.execute("ROLLBACK;")
                raise
            conn.execute("COMMIT;")

        self._update_token_json(token_id, {"consumed": True})


def compute_argv_digest(argv: list[str]) -> str:
    """Compute SHA256 digest of command argv array."""
    serialized = json.dumps(argv, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
