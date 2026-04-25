"""
Unit tests for src/crypto.py — EncryptedText TypeDecorator.
"""

import os
import pytest
from cryptography.fernet import Fernet
from unittest.mock import patch

from src.crypto import EncryptedText, _get_fernet


VALID_KEY = Fernet.generate_key().decode()
PLAINTEXT = "sk-test-api-key-1234"


@pytest.fixture(autouse=True)
def clear_fernet_env(monkeypatch):
    monkeypatch.delenv("LLM_ENCRYPTION_KEY", raising=False)


def _make_type():
    return EncryptedText()


# ── _get_fernet ──────────────────────────────────────────────────────────────

def test_get_fernet_returns_none_when_key_not_set():
    assert _get_fernet() is None


def test_get_fernet_returns_fernet_when_key_set(monkeypatch):
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", VALID_KEY)
    f = _get_fernet()
    assert f is not None


# ── process_bind_param (write path) ─────────────────────────────────────────

def test_bind_param_returns_none_for_none():
    t = _make_type()
    assert t.process_bind_param(None, None) is None


def test_bind_param_returns_plaintext_when_no_key():
    t = _make_type()
    result = t.process_bind_param(PLAINTEXT, None)
    assert result == PLAINTEXT


def test_bind_param_encrypts_when_key_set(monkeypatch):
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", VALID_KEY)
    t = _make_type()
    result = t.process_bind_param(PLAINTEXT, None)
    assert result != PLAINTEXT
    # Should be a valid Fernet token
    fernet = Fernet(VALID_KEY.encode())
    assert fernet.decrypt(result.encode()).decode() == PLAINTEXT


# ── process_result_value (read path) ────────────────────────────────────────

def test_result_value_returns_none_for_none():
    t = _make_type()
    assert t.process_result_value(None, None) is None


def test_result_value_returns_value_when_no_key():
    t = _make_type()
    result = t.process_result_value(PLAINTEXT, None)
    assert result == PLAINTEXT


def test_result_value_decrypts_encrypted_value(monkeypatch):
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", VALID_KEY)
    fernet = Fernet(VALID_KEY.encode())
    ciphertext = fernet.encrypt(PLAINTEXT.encode()).decode()

    t = _make_type()
    result = t.process_result_value(ciphertext, None)
    assert result == PLAINTEXT


def test_result_value_falls_back_to_plaintext_for_legacy_row(monkeypatch):
    """Pre-migration plaintext rows must be readable without crashing."""
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", VALID_KEY)
    t = _make_type()
    # PLAINTEXT is not a valid Fernet token; should fall back gracefully
    result = t.process_result_value(PLAINTEXT, None)
    assert result == PLAINTEXT


# ── Round-trip ───────────────────────────────────────────────────────────────

def test_round_trip(monkeypatch):
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", VALID_KEY)
    t = _make_type()
    stored = t.process_bind_param(PLAINTEXT, None)
    recovered = t.process_result_value(stored, None)
    assert recovered == PLAINTEXT


def test_empty_string_round_trip(monkeypatch):
    monkeypatch.setenv("LLM_ENCRYPTION_KEY", VALID_KEY)
    t = _make_type()
    stored = t.process_bind_param("", None)
    # Empty string treated same as None-ish — should not crash
    recovered = t.process_result_value(stored, None)
    assert recovered == "" or recovered is None
