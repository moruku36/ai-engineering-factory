"""Synthetic-only composition tests: no process, file, network, native API or prompt.

Run: C:\\path\\to\\python.exe -I -B
     C:\\path\\to\\checkout\\docs\\examples\\local-credential-broker\\launcher-bridge-mock.test.py
"""

import importlib.util
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
# Explicit trusted repo path; -I keeps cwd and the script directory off sys.path.
_REPO_ROOT = _HERE.parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.append(str(_REPO_ROOT))

_spec = importlib.util.spec_from_file_location(
    "launcher_bridge_mock", _HERE / "launcher-bridge-mock.py"
)
bridge = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bridge
_spec.loader.exec_module(bridge)

STATUSES = {
    "disabled", "ok", "denied", "failed", "cancelled", "expired", "cleanup_incomplete",
}
EVENTS = {"enroll", "grant", "execute", "lifecycle", "cleanup", "delete"}


def approval(operation=bridge.RUNPOD, approval_id="synthetic-approval"):
    return bridge.TrialApproval(
        approval_id, "synthetic-task", operation,
        bridge.SYNTHETIC_TARGET, 0.0, 200.0, bridge.SYNTHETIC_PLAN,
    )


class LauncherBridgeMockTest(unittest.TestCase):
    def setUp(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("no prompt, subprocess or native API in tests")
        for target in ("getpass.getpass", "subprocess.Popen", "subprocess.run", "os.system"):
            patcher = mock.patch(target, forbidden)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch("ctypes.WinDLL", forbidden, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.now = [100.0]
        self.prompts = []
        self.messages = []

    def hidden(self, prompt):
        self.prompts.append(prompt)
        return "synthetic-fixture"

    def harness(self, enabled=True, read_hidden=None):
        harness = bridge.TrustedLauncherBridgeMock(
            enabled=enabled, read_hidden=read_hidden or self.hidden,
            write_safe=self.messages.append, clock=lambda: self.now[0],
        )
        self.addCleanup(harness.close)
        return harness

    def enrolled(self):
        harness = self.harness()
        self.assertEqual(harness.enroll_once(), {"status": "ok"})
        return harness

    def events(self, harness):
        return [item["event"] for item in harness.audit_snapshot_trusted()]

    def assert_public_safe(self, harness, *results):
        for result in results:
            self.assertEqual(set(result), {"status"})
            self.assertIn(result["status"], STATUSES)
        audit = harness.audit_snapshot_trusted()
        for item in audit:
            self.assertEqual(set(item), {"event", "status"})
            self.assertIn(item["event"], EVENTS)
            self.assertIn(item["status"], STATUSES)
        cleanup = harness.cleanup_snapshot_trusted()
        self.assertTrue(all(type(value) is bool for value in cleanup.values()))
        # Enrollment UI text is excluded: its fixed instruction names the fixture word.
        text = json.dumps([results, audit, cleanup]) + repr(harness)
        for needle in ("synthetic-fixture", "provider payload", "RuntimeError", "Traceback"):
            self.assertNotIn(needle, text)

    def test_default_off_no_prompt_enrollment_or_grant(self):
        harness = bridge.TrustedLauncherBridgeMock(
            read_hidden=self.hidden, write_safe=self.messages.append,
            clock=lambda: self.now[0],
        )
        self.assertEqual(harness.enroll_once(), {"status": "disabled"})
        self.assertEqual(
            harness.run_once(approval(), trusted_task="synthetic-task"),
            {"status": "disabled"},
        )
        self.assertEqual(harness.close(), {"status": "disabled"})
        self.assertEqual((self.prompts, self.messages), ([], []))
        self.assertEqual(harness.audit_snapshot_trusted(), [])
        self.assertFalse(harness.store_available_trusted())
        with mock.patch("builtins.print") as printed:
            self.assertEqual(bridge.main([]), 0)
        self.assertIn("disabled", printed.call_args[0][0])

    def test_one_enrollment_two_separately_approved_fixed_operations(self):
        harness = self.enrolled()
        self.assertEqual(harness.enroll_once(), {"status": "denied"})
        self.assertEqual(len(self.prompts), 1)
        results = []
        for operation in (bridge.RUNPOD, bridge.MATTERMOST):
            results.append(harness.run_once(
                approval(operation, "approval-" + operation), trusted_task="synthetic-task"
            ))
            self.assertEqual(results[-1], {"status": "ok"})
            cleanup = harness.cleanup_snapshot_trusted()
            self.assertTrue(cleanup and all(cleanup.values()))
        self.assertEqual(set(cleanup), {
            "active_zero", "protected_zero", "read_cap_respected", "event_cap_respected",
        })
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.events(harness).count("lifecycle"), 2)
        self.assert_public_safe(harness, *results)

    def test_invalid_input_reaches_no_downstream(self):
        harness = self.enrolled()
        good = approval()
        invalid = [
            (object(), None), ({"operation": bridge.RUNPOD}, None),
            (replace(good, operation="runpod.start.unbounded"), None),
            (replace(good, target_ref="other"), None),
            (replace(good, plan_digest="other"), None),
            (replace(good, budget_cap=10.0), None),
            (replace(good, budget_cap=True), None),
            (replace(good, deadline=float("inf")), None),
            (good, "unknown-fault"), (good, lambda: None),
        ]
        for candidate, fault in invalid:
            self.assertEqual(
                harness.run_once(candidate, trusted_task="synthetic-task", fault=fault),
                {"status": "denied"},
            )
        self.assertEqual(set(self.events(harness)), {"enroll", "grant"})
        self.assertEqual(harness.cleanup_snapshot_trusted(), {})
        # The rejected attempts did not consume the valid approval.
        self.assertEqual(
            harness.run_once(good, trusted_task="synthetic-task"), {"status": "ok"}
        )

    def test_replay_expired_and_cross_task_denied(self):
        harness = self.enrolled()
        first = approval()
        self.assertEqual(
            harness.run_once(first, trusted_task="synthetic-task"), {"status": "ok"}
        )
        denied = [
            harness.run_once(first, trusted_task="synthetic-task"),
            harness.run_once(
                replace(first, approval_id="expired", deadline=100.0),
                trusted_task="synthetic-task",
            ),
            harness.run_once(
                replace(first, approval_id="cross-task"), trusted_task="other-task"
            ),
            # A denied cross-task attempt still burns the approval; no auto-refresh.
            harness.run_once(
                replace(first, approval_id="cross-task"), trusted_task="synthetic-task"
            ),
        ]
        self.assertEqual(denied, [{"status": "denied"}] * 4)
        self.assertEqual(self.events(harness).count("lifecycle"), 1)
        self.now[0] = 500.0
        self.assertEqual(
            harness.run_once(
                replace(first, approval_id="late"), trusted_task="synthetic-task"
            ),
            {"status": "denied"},
        )
        self.assert_public_safe(harness, *denied)

    def test_fake_failure_preserves_cleanup_and_serializes_nothing(self):
        harness = self.enrolled()
        cases = [
            (bridge.RUNPOD, "runpod.run", "failed", True),
            (bridge.MATTERMOST, "mattermost.monitor", "failed", True),
            (bridge.RUNPOD, "cancel", "cancelled", True),
            (bridge.MATTERMOST, "cancel", "cancelled", True),
            (bridge.RUNPOD, "runpod.pod_cleanup", "cleanup_incomplete", False),
            (bridge.MATTERMOST, "mattermost.stop", "cleanup_incomplete", False),
        ]
        results = []
        for index, (operation, fault, status, clean) in enumerate(cases):
            results.append(harness.run_once(
                approval(operation, f"approval-{index}"),
                trusted_task="synthetic-task", fault=fault,
            ))
            self.assertEqual(results[-1], {"status": status})
            cleanup = harness.cleanup_snapshot_trusted()
            self.assertEqual(all(cleanup.values()), clean)
            if operation == bridge.RUNPOD:
                # Journal close is tracked separately from Pod absence.
                self.assertTrue(cleanup["journal_closed"])
                self.assertEqual(cleanup["pod_absent"], clean)
            else:
                self.assertTrue(cleanup["active_zero"])
                self.assertEqual(cleanup["protected_zero"], clean)
        self.assertEqual(self.events(harness).count("cleanup"), len(cases))
        self.assert_public_safe(harness, *results)

    def test_close_deletes_store_and_fails_closed(self):
        harness = self.enrolled()
        self.assertTrue(harness.store_available_trusted())
        try:
            with harness:
                raise RuntimeError("synthetic failure inside trusted block")
        except RuntimeError:
            pass
        self.assertFalse(harness.store_available_trusted())
        self.assertEqual(
            harness.run_once(approval(), trusted_task="synthetic-task"),
            {"status": "denied"},
        )
        self.assertEqual(harness.enroll_once(), {"status": "denied"})
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(harness.close(), {"status": "ok"})
        self.assert_public_safe(harness)

    def test_deadline_reached_during_fake_lifecycle_expires_with_cleanup(self):
        harness = self.enrolled()
        granted = approval()
        original = bridge._placeholder_reader
        roles = []

        def advancing_reader(role):
            # Test-only: runs after the broker accepted, before fake run_injected.
            roles.append(role)
            self.now[0] = granted.deadline
            return original(role)

        with mock.patch.object(bridge, "_placeholder_reader", advancing_reader):
            result = harness.run_once(granted, trusted_task="synthetic-task")
        self.assertEqual(result, {"status": "expired"})
        self.assertEqual(tuple(roles), bridge._RUNPOD_ROLES)
        self.assertEqual(roles[-1], "journal signing key hex")
        self.assertEqual(
            harness.cleanup_snapshot_trusted(),
            {"journal_closed": True, "pod_absent": True},
        )
        self.assertEqual(harness.audit_snapshot_trusted()[1:], [
            {"event": "execute", "status": "ok"},
            {"event": "cleanup", "status": "ok"},
            {"event": "lifecycle", "status": "expired"},
        ])
        self.assert_public_safe(harness, result)

    def assert_rejected_enrollment_isolated(self, read_hidden, needle):
        reached = []

        def recording(*args, **kwargs):
            # Recorded, not raised: run_once would swallow an exception from a fake.
            reached.append(None)
            return False, {}

        harness = self.harness(read_hidden=read_hidden)
        with (
            mock.patch.dict(bridge._SHAPES, {name: recording for name in bridge._SHAPES}),
            mock.patch.object(bridge, "_placeholder_reader", recording),
        ):
            results = [harness.enroll_once()]
            self.assertIn(results[0]["status"], {"denied", "failed"})
            for operation in (bridge.RUNPOD, bridge.MATTERMOST):
                results.append(harness.run_once(
                    approval(operation, "approval-" + operation),
                    trusted_task="synthetic-task",
                ))
                self.assertEqual(results[-1], {"status": "denied"})
            results.append(harness.enroll_once())
            self.assertEqual(results[-1], {"status": "denied"})
        self.assertEqual(reached, [])
        self.assertEqual(set(self.events(harness)), {"enroll", "grant"})
        self.assertEqual(harness.cleanup_snapshot_trusted(), {})
        self.assertFalse(harness.store_available_trusted())
        self.assert_public_safe(harness, *results)
        text = json.dumps([
            results, harness.audit_snapshot_trusted(),
            harness.cleanup_snapshot_trusted(), self.messages,
        ]) + repr(harness)
        self.assertNotIn(needle, text)

    def test_nonsynthetic_owner_input_reaches_no_fake_or_downstream(self):
        def nonsynthetic(prompt):
            self.prompts.append(prompt)
            return "nonsynthetic-owner-input"

        self.assert_rejected_enrollment_isolated(nonsynthetic, "nonsynthetic-owner-input")
        self.assertEqual(len(self.prompts), 1)

    def test_hidden_callback_exception_reaches_no_fake_or_downstream(self):
        def raising(prompt):
            self.prompts.append(prompt)
            raise RuntimeError("hidden-callback-detail")

        self.assert_rejected_enrollment_isolated(raising, "hidden-callback-detail")
        self.assertEqual(len(self.prompts), 1)


    def test_mm_fake_inherits_grant_total_cap_and_earlier_owner_deadline(self):
        harness = self.enrolled()
        seen = []
        def shape(context, fault):
            seen.append(context)
            return True, {"active_zero": True, "protected_zero": True}
        with mock.patch.dict(bridge._SHAPES, {bridge.MATTERMOST: shape}):
            granted = replace(approval(bridge.MATTERMOST), deadline=1000.0)
            self.assertEqual(
                harness.run_once(granted, trusted_task="synthetic-task"), {"status": "ok"}
            )
            self.assertEqual(seen[0]._deadline, 400.0)
            granted = replace(granted, approval_id="second", deadline=150.0)
            self.assertEqual(
                harness.run_once(granted, trusted_task="synthetic-task"), {"status": "ok"}
            )
            self.assertEqual(seen[1]._deadline, 150.0)

    def test_mm_preparation_and_monitor_are_distinct_under_total_cap(self):
        cancel = bridge.threading.Event()
        context = bridge._LifecycleContext(cancel, lambda: self.now[0], 400.0)
        preparation = context.phase(bridge.MM_PREPARATION_CAP)
        self.assertEqual(preparation._deadline, 400.0)
        self.now[0] = 350.0
        monitor = context.phase(bridge.MM_MONITOR_CAP)
        self.assertIsNot(preparation, monitor)
        self.assertEqual(monitor._deadline, 400.0)
        self.now[0] = 400.0
        self.assertTrue(monitor.stopped())

    def test_cancel_during_broker_preflight_is_not_reset_before_fake(self):
        from concurrent.futures import ThreadPoolExecutor

        harness = self.enrolled()
        entered, release = bridge.threading.Event(), bridge.threading.Event()
        original = bridge.BoundedMockBroker.execute
        def paused(broker, request, *, trusted_task):
            entered.set()
            if not release.wait(3):
                raise AssertionError("test release timeout")
            return original(broker, request, trusted_task=trusted_task)
        with mock.patch.object(bridge.BoundedMockBroker, "execute", paused):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    harness.run_once, approval(), trusted_task="synthetic-task"
                )
                self.assertTrue(entered.wait(3))
                harness.cancel_trusted()
                release.set()
                self.assertEqual(future.result(timeout=3), {"status": "cancelled"})
        self.assertTrue(all(harness.cleanup_snapshot_trusted().values()))
        self.assert_public_safe(harness)


if __name__ == "__main__":
    unittest.main()
