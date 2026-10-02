"""Read-only local packet collection with an explicitly separate coordinator record."""

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from orchestrator.core.handoff import HandoffError, collect_receipt, load_json


def publish_receipt(path, receipt):
    """Encode completely, then publish a complete file atomically without replacement."""
    try:
        content = (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    except UnicodeError as exc:
        raise HandoffError("Receipt contains invalid Unicode") from exc
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".receipt-", suffix=".tmp", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-directory hard link creation is atomic and refuses any existing path.
        # Unsupported filesystems fail closed; do not fall back to overwriting rename.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--trust", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        packet = args.packet.resolve()
        if args.trust.resolve().is_relative_to(packet):
            raise HandoffError("Trusted record must be outside the received packet")
        if args.receipt.resolve().is_relative_to(packet):
            raise HandoffError("Receipt must be outside the received packet")
        with args.trust.open("rb") as stream:
            trust = load_json(stream.read(1024 * 1024 + 1))
        receipt = collect_receipt(args.packet, trust)
        receipt["received_at"] = datetime.now(UTC).isoformat()
        publish_receipt(args.receipt, receipt)
    except (HandoffError, OSError) as exc:
        print(f"BLOCKED_CAPABILITY: {exc}", file=sys.stderr)
        return 2
    print("COLLECTED: receipt written; acceptance verification remains unknown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
