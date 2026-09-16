"""Ephemeral keys for approval fixtures only; never an operational credential."""

import secrets

import pytest


@pytest.fixture(autouse=True)
def isolated_test_approval_key(monkeypatch):
    # Spawned fixture processes inherit this random test key.
    monkeypatch.setenv("AI_FACTORY_APPROVAL_SECRET", secrets.token_hex(32))
