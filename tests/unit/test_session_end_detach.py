from __future__ import annotations

import io
import json
import os
import sys

import pytest


def _neutralize_child_detach(hook_module, monkeypatch):
    """Stop the child branch from detaching the test process itself."""
    monkeypatch.setattr(os, "setsid", lambda: None, raising=False)
    monkeypatch.setattr(os, "open", lambda *a, **k: 3, raising=False)
    monkeypatch.setattr(os, "dup2", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(os, "close", lambda *a, **k: None, raising=False)


def test_parent_reports_true_after_a_successful_fork(hook_module, monkeypatch):
    monkeypatch.setattr(hook_module, "SYNC_SESSION_END", False)
    monkeypatch.setattr(os, "fork", lambda: 4242, raising=False)

    assert hook_module._detach_from_cli() is True


def test_child_reports_false_and_leaves_the_process_group(hook_module, monkeypatch):
    monkeypatch.setattr(hook_module, "SYNC_SESSION_END", False)
    monkeypatch.setattr(os, "fork", lambda: 0, raising=False)
    calls = []
    monkeypatch.setattr(os, "setsid", lambda: calls.append("setsid"), raising=False)
    monkeypatch.setattr(os, "open", lambda *a, **k: 7, raising=False)
    monkeypatch.setattr(os, "dup2", lambda fd, target: calls.append(f"dup2:{target}"), raising=False)
    monkeypatch.setattr(os, "close", lambda fd: calls.append("close"), raising=False)

    assert hook_module._detach_from_cli() is False
    assert "setsid" in calls
    assert {"dup2:0", "dup2:1", "dup2:2"} <= set(calls)


def test_fork_failure_keeps_the_run_in_the_foreground(hook_module, monkeypatch):
    monkeypatch.setattr(hook_module, "SYNC_SESSION_END", False)

    def _boom():
        raise OSError("no resources")

    monkeypatch.setattr(os, "fork", _boom, raising=False)

    assert hook_module._detach_from_cli() is False


def test_sync_option_keeps_the_run_in_the_foreground(hook_module, monkeypatch):
    monkeypatch.setattr(hook_module, "SYNC_SESSION_END", True)

    def _unexpected():
        raise AssertionError("fork must not run when the sync option is set")

    monkeypatch.setattr(os, "fork", _unexpected, raising=False)

    assert hook_module._detach_from_cli() is False


def _prepare_run_with_work(hook_module, monkeypatch, tmp_path, event_name):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    payload = {"sessionId": "s1", "transcriptPath": str(transcript)}
    if event_name:
        payload["hookEventName"] = event_name
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    return transcript


def test_session_end_parent_returns_before_it_builds_a_client(
    hook_module, isolated_hook_state, tmp_path, monkeypatch
):
    _prepare_run_with_work(hook_module, monkeypatch, tmp_path, "SessionEnd")
    monkeypatch.setattr(hook_module, "_detach_from_cli", lambda: True)

    def _unexpected(*args, **kwargs):
        raise AssertionError("the parent must not touch langfuse")

    monkeypatch.setattr(hook_module, "create_langfuse_client", _unexpected)

    assert hook_module.main() == 0


def test_session_end_child_does_the_work(hook_module, isolated_hook_state, tmp_path, monkeypatch):
    _prepare_run_with_work(hook_module, monkeypatch, tmp_path, "SessionEnd")
    monkeypatch.setattr(hook_module, "_detach_from_cli", lambda: False)
    calls = []
    monkeypatch.setattr(hook_module, "create_langfuse_client", lambda config: calls.append(config))

    assert hook_module.main() == 0
    assert len(calls) == 1


def test_stop_run_never_detaches(hook_module, isolated_hook_state, tmp_path, monkeypatch):
    _prepare_run_with_work(hook_module, monkeypatch, tmp_path, "Stop")

    def _unexpected():
        raise AssertionError("a Stop run must keep the foreground")

    monkeypatch.setattr(hook_module, "_detach_from_cli", _unexpected)
    monkeypatch.setattr(hook_module, "create_langfuse_client", lambda config: None)

    assert hook_module.main() == 0


def test_a_run_with_no_work_never_detaches(hook_module, isolated_hook_state, tmp_path, monkeypatch):
    transcript = _prepare_run_with_work(hook_module, monkeypatch, tmp_path, "SessionEnd")
    state = hook_module.load_hook_state()
    key = hook_module.get_session_state_key("s1", str(transcript))
    session_state = hook_module.get_session_state(state, key)
    session_state.offset = transcript.stat().st_size
    hook_module.save_session_state(state, key, session_state)

    def _unexpected():
        raise AssertionError("the fast path must return before the fork")

    monkeypatch.setattr(hook_module, "_detach_from_cli", _unexpected)

    assert hook_module.main() == 0
