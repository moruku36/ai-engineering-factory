import fnmatch
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class ArtifactExtractionError(Exception):
    """Raised when an artifact violates safety bounds, size limits, or path policies."""


# Critical files that must never be created, overwritten, or modified by workers
PROTECTED_CONTROL_PATHS = {
    ".git", ".git/config", ".git/hooks", "HEAD", "state", "runtime-root",
    "approvals.sqlite", "executions.sqlite", "leases.sqlite",
    ".env", "id_rsa", "id_ed25519", "operator.key",
}


@dataclass(frozen=True)
class ArtifactCollectionResult:
    collected_files: dict[str, str]  # rel_path -> sha256
    total_bytes: int
    manifest_digest: str


class ArtifactCollector:
    """Safely inspects and copies artifacts from an untrusted container/worker directory into a control area."""

    def __init__(
        self,
        allowed_paths: list[str] | None = None,
        max_file_size: int = 1024 * 1024,  # 1 MiB per file
        max_total_size: int = 10 * 1024 * 1024,  # 10 MiB total
        allowed_extensions: set[str] | None = None,
    ):
        self.allowed_paths = [p.replace("\\", "/").strip("/") for p in (allowed_paths or ["*"])]
        self.max_file_size = max_file_size
        self.max_total_size = max_total_size
        self.allowed_extensions = {ext.lower() for ext in allowed_extensions} if allowed_extensions else None

    def _is_path_allowed(self, rel_path: str) -> bool:
        if "*" in self.allowed_paths:
            return True
        norm = rel_path.replace("\\", "/").strip("/")
        for pattern in self.allowed_paths:
            clean_pat = pattern.rstrip("/")
            if fnmatch.fnmatch(norm, pattern) or fnmatch.fnmatch(norm, clean_pat):
                return True
            if "*" not in clean_pat and (norm == clean_pat or norm.startswith(clean_pat + "/")):
                return True
        return False

    def collect(self, source_dir: Path | str, target_dir: Path | str) -> ArtifactCollectionResult:
        src = Path(source_dir).resolve()
        dst = Path(target_dir).resolve()

        if not src.exists() or not src.is_dir():
            raise ArtifactExtractionError(f"Artifact source directory does not exist: {src}")

        dst.mkdir(parents=True, exist_ok=True)

        collected: dict[str, str] = {}
        total_bytes = 0

        for root, dirs, files in os.walk(src, followlinks=False):
            # Check for directory symlinks
            for d in dirs:
                full_d = Path(root) / d
                if full_d.is_symlink():
                    raise ArtifactExtractionError(f"Directory symlink detected and rejected: {full_d.name}")

            for f in files:
                full_f = Path(root) / f

                # Symlinks are strictly forbidden
                if full_f.is_symlink():
                    raise ArtifactExtractionError(f"Symlink detected and rejected: {full_f}")

                # Must be a regular file
                if not full_f.is_file():
                    raise ArtifactExtractionError(f"Non-regular file detected: {full_f}")

                rel = full_f.relative_to(src)
                rel_posix = rel.as_posix()

                # Traversal check on relative path components
                pure = PurePosixPath(rel_posix)
                if pure.is_absolute() or ".." in pure.parts or any(p in ("", ".") for p in pure.parts):
                    raise ArtifactExtractionError(f"Path traversal or invalid path: {rel_posix}")

                # Check protected control paths
                for part in pure.parts:
                    if part in PROTECTED_CONTROL_PATHS or part.startswith(".git"):
                        raise ArtifactExtractionError(f"Access to protected control path denied: {rel_posix}")

                # Extension check
                if self.allowed_extensions is not None:
                    suffix = pure.suffix.lower()
                    if suffix not in self.allowed_extensions:
                        raise ArtifactExtractionError(
                            f"File extension '{suffix}' not allowed for {rel_posix}"
                        )

                # Allowed paths check
                if not self._is_path_allowed(rel_posix):
                    raise ArtifactExtractionError(f"Path '{rel_posix}' is not in allowed_paths")

                # Size checks
                file_size = full_f.stat().st_size
                if file_size > self.max_file_size:
                    raise ArtifactExtractionError(
                        f"File '{rel_posix}' size {file_size} exceeds maximum {self.max_file_size}"
                    )

                total_bytes += file_size
                if total_bytes > self.max_total_size:
                    raise ArtifactExtractionError(
                        f"Total artifact size {total_bytes} exceeds limit {self.max_total_size}"
                    )

                # Compute content digest
                content = full_f.read_bytes()
                digest = hashlib.sha256(content).hexdigest()

                # Target copy destination check
                out_path = (dst / rel).resolve()
                try:
                    out_path.relative_to(dst)
                except ValueError as exc:
                    raise ArtifactExtractionError(f"Destination escape detected: {out_path}") from exc

                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(content)
                collected[rel_posix] = digest

        # Compute deterministic overall manifest digest
        canonical_items = sorted(collected.items())
        manifest_raw = "\n".join(f"{path}:{sha}" for path, sha in canonical_items)
        manifest_digest = hashlib.sha256(manifest_raw.encode("utf-8")).hexdigest()

        return ArtifactCollectionResult(
            collected_files=collected,
            total_bytes=total_bytes,
            manifest_digest=manifest_digest,
        )
