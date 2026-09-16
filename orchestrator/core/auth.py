"""Authentication, authorization, and cryptographic identity verification for human approvers."""

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class AuthenticationError(Exception):
    """Raised when approver identity cannot be verified or credentials are invalid."""


class AuthorizationError(Exception):
    """Raised when an authenticated approver lacks required action permissions."""


def derive_key_fingerprint(key: bytes | str) -> str:
    """Derive deterministic public key identifier (fingerprint) from secret key."""
    if isinstance(key, str):
        key = key.encode("utf-8")
    if len(key) < 32:
        raise AuthenticationError("Operator secret key must be at least 32 bytes")
    digest = hashlib.sha256(key).hexdigest()[:32]
    return f"key-{digest}"


def compute_operator_signature(token_data: dict[str, Any], operator_key: bytes | str) -> str:
    """Compute HMAC-SHA256 signature with approver's personal private key."""
    if isinstance(operator_key, str):
        operator_key = operator_key.encode("utf-8")
    if len(operator_key) < 32:
        raise AuthenticationError("Operator secret key must be at least 32 bytes")

    signed_fields = (
        "action", "repository", "task_id", "head_sha", "target_ref",
        "argv_digest", "policy_hash", "plan_hash", "approved_by",
    )
    canonical = json.dumps(
        {k: token_data[k] for k in signed_fields if k in token_data},
        sort_keys=True, separators=(",", ":")
    )
    return hmac.new(operator_key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class ApproverIdentity:
    user_id: str
    role: str
    key_fingerprint: str
    allowed_actions: list[str] = field(default_factory=list)
    revoked: bool = False


class ApproverRegistry:
    """Registry managing authorized human approvers, public key fingerprints, and permissions."""

    def __init__(self, config_path: Path | str | None = None, approvers: list[dict[str, Any]] | None = None):
        self._approvers: dict[str, ApproverIdentity] = {}
        self._configured = False

        if approvers is not None:
            for item in approvers:
                self.register(ApproverIdentity(**item))
            self._configured = True
        elif config_path is not None and Path(config_path).exists():
            self._load_config(Path(config_path))
            self._configured = True
        elif os.environ.get("AI_FACTORY_APPROVERS_CONFIG"):
            raw = os.environ["AI_FACTORY_APPROVERS_CONFIG"]
            if Path(raw).exists():
                self._load_config(Path(raw))
            else:
                try:
                    data = json.loads(raw)
                    for item in data:
                        self.register(ApproverIdentity(**item))
                except Exception as exc:
                    raise AuthenticationError(f"Failed to parse AI_FACTORY_APPROVERS_CONFIG: {exc}") from exc
            self._configured = True

    def _load_config(self, path: Path) -> None:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                self.register(ApproverIdentity(**item))
        except Exception as exc:
            raise AuthenticationError(f"Failed to load approver config from {path}: {exc}") from exc

    @property
    def is_configured(self) -> bool:
        return self._configured

    def register(self, identity: ApproverIdentity) -> None:
        self._approvers[identity.user_id] = identity
        self._configured = True

    def revoke(self, user_id: str) -> None:
        if user_id in self._approvers:
            curr = self._approvers[user_id]
            self._approvers[user_id] = ApproverIdentity(
                user_id=curr.user_id,
                role=curr.role,
                key_fingerprint=curr.key_fingerprint,
                allowed_actions=curr.allowed_actions,
                revoked=True,
            )

    def get_identity(self, user_id: str) -> ApproverIdentity | None:
        return self._approvers.get(user_id)

    def authenticate_and_authorize(
        self,
        user_id: str,
        operator_key: bytes | str,
        action: str,
    ) -> str:
        """Authenticate user by key fingerprint and authorize for action. Returns key_fingerprint."""
        if not self.is_configured:
            raise AuthenticationError("Approver authentication infrastructure is not configured (BLOCKED)")

        identity = self.get_identity(user_id)
        if not identity:
            raise AuthenticationError(f"Approver '{user_id}' is not in the authorized approvers registry")

        if identity.revoked:
            raise AuthenticationError(f"Approver '{user_id}' has been revoked")

        fp = derive_key_fingerprint(operator_key)
        if not hmac.compare_digest(fp, identity.key_fingerprint):
            raise AuthenticationError(f"Cryptographic key fingerprint mismatch for approver '{user_id}'")

        # Check action permission ("*" allows all, or exact match)
        if "*" not in identity.allowed_actions and action not in identity.allowed_actions:
            raise AuthorizationError(f"Approver '{user_id}' lacks authorization for action '{action}'")

        return fp

    def verify_token_identity(
        self,
        user_id: str,
        key_id: str,
        action: str,
    ) -> None:
        """Verify that token was issued by a currently valid, non-revoked approver with matching key_id."""
        if not self.is_configured:
            raise AuthenticationError("Approver authentication infrastructure is not configured (BLOCKED)")

        identity = self.get_identity(user_id)
        if not identity:
            raise AuthenticationError(f"Token approver '{user_id}' is not recognized")

        if identity.revoked:
            raise AuthenticationError(f"Token approver '{user_id}' credentials have been revoked")

        if not hmac.compare_digest(key_id, identity.key_fingerprint):
            raise AuthenticationError(f"Token key ID '{key_id}' does not match registered key for '{user_id}'")

        if "*" not in identity.allowed_actions and action not in identity.allowed_actions:
            raise AuthorizationError(f"Token approver '{user_id}' not authorized for action '{action}'")
