"""Owner enrollment UX prototype: synthetic input only, mock store only.

No Windows backend activation, persistent storage or automatic service/launcher start.
Run manually with python -m orchestrator.credential_enrollment_mock.
"""

import getpass
import sys

from orchestrator.local_credential_broker import MockCredentialStore
from orchestrator.windows_credential_store import wipe


def run_mock_enrollment(read_hidden, write_safe, store):
    """Trusted UI callbacks. Never register this function as a model tool."""
    if type(store) is not MockCredentialStore:
        write_safe("mock store required")
        return {"status": "denied"}
    value = bytearray()
    try:
        write_safe("MOCK ONLY: enter synthetic-fixture; no real credentials")
        answer = read_hidden("Synthetic registration (hidden, blank cancels): ")
        if not answer:
            write_safe("registration cancelled")
            return {"status": "cancelled"}
        if answer != "synthetic-fixture":
            write_safe("synthetic input required")
            return {"status": "denied"}
        value = bytearray(answer, "utf-8")
        del answer
        store.write(value)
        write_safe("mock registration complete; no persistent storage")
        return {"status": "ok"}
    except (KeyboardInterrupt, EOFError):
        write_safe("registration cancelled")
        return {"status": "cancelled"}
    except Exception:  # noqa: BLE001 - UI/store exceptions must not echo input
        write_safe("mock registration failed")
        return {"status": "failed"}
    finally:
        wipe(value)


def main():
    # Refuse getpass fallback: it may echo input on a noninteractive stream.
    if not sys.stdin.isatty():
        print("interactive mock input required; no registration performed")
        return 2
    store = MockCredentialStore()
    try:
        result = run_mock_enrollment(getpass.getpass, print, store)
        return 0 if result["status"] == "ok" else 1
    finally:
        store.delete()  # Demo is process-only; always clean up.
        print("mock data deleted")


if __name__ == "__main__":
    raise SystemExit(main())
