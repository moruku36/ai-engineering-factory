"""The scanner must not confuse an adjacent dummy fixture with a secret exception."""

from unittest.mock import MagicMock, patch

from scripts.secret_scan import scan_all, scan_text


def test_fixture_substring_does_not_hide_another_secret():
    synthetic = "ghp_" + "Z" * 36
    assert scan_text("ghp_secret12345 " + synthetic, "fixture")


def test_complete_head_tree_is_scanned_when_diff_is_empty():
    synthetic = "ghp_" + "Z" * 36
    calls = []

    def git(args, **kwargs):
        calls.append(args)
        return MagicMock(returncode=0, stdout=synthetic if "grep" in args else "", stderr="")

    with patch("scripts.secret_scan.subprocess.run", side_effect=git):
        assert scan_all() == 1
    assert any("log" in args for args in calls)


def test_tree_scan_error_is_not_empty_success():
    def git(args, **kwargs):
        return MagicMock(returncode=2 if "grep" in args else 0, stdout="", stderr="")

    with patch("scripts.secret_scan.subprocess.run", side_effect=git):
        assert scan_all() == 2
