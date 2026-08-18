from __future__ import annotations


def _write_state(hook_module, session_id, transcript_path, **entry_overrides):
    state = hook_module.load_hook_state()
    key = hook_module.get_session_state_key(session_id, str(transcript_path))
    session_state = hook_module.get_session_state(state, key)
    for field_name, value in entry_overrides.items():
        setattr(session_state, field_name, value)
    hook_module.save_session_state(state, key, session_state)


def test_no_pending_work_when_offset_matches_file_size_and_nothing_deferred(
    hook_module, isolated_hook_state, tmp_path
):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(hook_module, "s1", transcript, offset=transcript.stat().st_size)

    assert hook_module._has_pending_work("s1", transcript) is False


def test_pending_work_when_transcript_has_unread_bytes(hook_module, isolated_hook_state, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(hook_module, "s1", transcript, offset=0)

    assert hook_module._has_pending_work("s1", transcript) is True


def test_pending_work_when_agent_turns_are_deferred(hook_module, isolated_hook_state, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(
        hook_module,
        "s1",
        transcript,
        offset=transcript.stat().st_size,
        pending_agent_turns=[{"turn": 1}],
    )

    assert hook_module._has_pending_work("s1", transcript) is True


def test_pending_work_when_task_notifications_are_unresolved(hook_module, isolated_hook_state, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(
        hook_module,
        "s1",
        transcript,
        offset=transcript.stat().st_size,
        pending_task_notifications=[{"tool_use_id": "abc"}],
    )

    assert hook_module._has_pending_work("s1", transcript) is True


def test_pending_work_when_open_turn_is_held(hook_module, isolated_hook_state, tmp_path):
    # The state can hold an open turn between two Stop runs. The transcript has
    # no new bytes in this condition. The check must find work to do, because
    # SessionEnd must complete the turn.
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(
        hook_module,
        "s1",
        transcript,
        offset=transcript.stat().st_size,
        open_turn={"user_row_uuid": "u1", "rows": [{"type": "user", "uuid": "u1"}]},
    )

    assert hook_module._has_pending_work("s1", transcript) is True


def _age_state_entry(hook_module, session_id, transcript_path, days):
    """Set the 'updated' timestamp of the entry back by the given days."""
    import datetime as dt
    import json

    state = hook_module.load_hook_state()
    key = hook_module.get_session_state_key(session_id, str(transcript_path))
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    state[key]["updated"] = old.isoformat()
    hook_module.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def test_caught_up_session_with_old_timestamp_is_pending(hook_module, isolated_hook_state, tmp_path):
    # A skipped run does not write the state file, but save_hook_state drops
    # entries that got no write for 30 days. An old entry must take the normal
    # path so that the entry stays alive.
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(hook_module, "s1", transcript, offset=transcript.stat().st_size)
    _age_state_entry(hook_module, "s1", transcript, days=8)

    assert hook_module._has_pending_work("s1", transcript) is True


def test_caught_up_session_without_timestamp_still_skips(hook_module, isolated_hook_state, tmp_path):
    # Entries without a parsable 'updated' timestamp are never pruned, and thus
    # the skip is safe for them.
    import json

    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(hook_module, "s1", transcript, offset=transcript.stat().st_size)

    state = hook_module.load_hook_state()
    key = hook_module.get_session_state_key("s1", str(transcript))
    del state[key]["updated"]
    hook_module.STATE_FILE.write_text(json.dumps(state), encoding="utf-8")

    assert hook_module._has_pending_work("s1", transcript) is False


def test_pending_work_defaults_true_for_unknown_session(hook_module, isolated_hook_state, tmp_path):
    # This session has no entry in the state file. A user can delete the state
    # file, or two hooks can run at the same time. In these conditions the check
    # must fail open and use the normal path. If it does not, the hook can lose
    # data.
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("", encoding="utf-8")

    assert hook_module._has_pending_work("never-seen", transcript) is True


def test_main_skips_langfuse_client_creation_when_nothing_pending(
    hook_module, isolated_hook_state, tmp_path, monkeypatch
):
    import io
    import json
    import sys

    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(hook_module, "s1", transcript, offset=transcript.stat().st_size)

    monkeypatch.setattr(
        sys, "stdin", io.StringIO(json.dumps({"sessionId": "s1", "transcriptPath": str(transcript)}))
    )
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    called = False

    def _boom(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("create_langfuse_client should not run when nothing is pending")

    monkeypatch.setattr(hook_module, "create_langfuse_client", _boom)

    assert hook_module.main() == 0
    assert called is False


def test_main_takes_real_path_when_open_turn_is_held(
    hook_module, isolated_hook_state, tmp_path, monkeypatch
):
    import io
    import json
    import sys

    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    _write_state(
        hook_module,
        "s1",
        transcript,
        offset=transcript.stat().st_size,
        open_turn={"user_row_uuid": "u1", "rows": [{"type": "user", "uuid": "u1"}]},
    )

    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {"sessionId": "s1", "transcriptPath": str(transcript), "hookEventName": "SessionEnd"}
            )
        ),
    )
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")

    called = False

    def _fake_client(*args, **kwargs):
        nonlocal called
        called = True
        return None  # main() stops here and sends no data

    monkeypatch.setattr(hook_module, "create_langfuse_client", _fake_client)

    assert hook_module.main() == 0
    assert called is True
