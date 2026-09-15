"""Approval token management and cryptographic verification engine."""

import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from orchestrator.core.schema import validate_against_schema


class ApprovalVerificationError(Exception):
    """Raised when an approval token fails validation, is tampered with, or expired."""


class ApprovalReplayError(ApprovalVerificationError):
    """Raised when an approval token is reused (replay attack)."""


class ApprovalExpiredError(ApprovalVerificationError):
    """Raised when an approval token has expired."""


class ApprovalManager:
    """Issues and verifies single-use approval tokens cryptographically bound to execution context."""

    def __init__(self, approvals_dir: Path | str | None = None):
        if approvals_dir is None:
            self.approvals_dir = Path(__file__).resolve().parent.parent.parent / "state" / "approvals"
        else:
            self.approvals_dir = Path(approvals_dir)
        self.approvals_dir.mkdir(parents=True, exist_ok=True)

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
        token_path = self._get_token_path(token_id)
        temp_path = token_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)
        os.replace(temp_path, token_path)

        return token_data

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
        """Verify all bound attributes and consume token immediately. Raises on mismatch or reuse."""
        token_path = self._get_token_path(token_id)
        if not token_path.exists():
            raise ApprovalVerificationError(f"Approval token '{token_id}' not found or forged")

        with open(token_path, "r", encoding="utf-8") as f:
            token_data = json.load(f)

        validate_against_schema(token_data, "approval.schema.json")

        if token_data["consumed"]:
            raise ApprovalReplayError(f"Approval token '{token_id}' has already been consumed")

        # Expiry check
        now = datetime.now(UTC)
        exp = datetime.fromisoformat(token_data["expires_at"])
        if now > exp:
            raise ApprovalExpiredError(f"Approval token '{token_id}' expired at {token_data['expires_at']}")

        # Attribute binding checks
        bindings = {
            "action": action,
            "repository": repository,
            "task_id": task_id,
            "head_sha": head_sha,
            "target_ref": target_ref,
            "argv_digest": argv_digest,
            "policy_hash": policy_hash,
            "plan_hash": plan_hash,
        }

        for attr, expected in bindings.items():
            actual = token_data.get(attr)
            if actual != expected:
                raise ApprovalVerificationError(
                    f"Token binding mismatch on '{attr}': expected '{expected}', found in token '{actual}'"
                )

        # Mark consumed atomically
        token_data["consumed"] = True
        temp_path = token_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2)
        os.replace(temp_path, token_path)


def compute_argv_digest(argv: list[str]) -> str:
    """Compute SHA256 digest of command argv array."""
    serialized = json.dumps(argv, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
