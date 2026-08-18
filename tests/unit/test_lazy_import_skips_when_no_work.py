from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_hook_module_without_forcing_import(monkeypatch, tmp_path):
    """Load a new copy of the hook module, but do not start the SDK import.

    The tests must check the import state after main() runs. The shared
    hook_module fixture always starts the import, and thus it hides this
    behavior. Home points to tmp_path. Thus the module writes no file in the
    real home directory of the user.
    """
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    module_path = REPO_ROOT / "hooks" / "langfuse_hook.py"
    spec = importlib.util.spec_from_file_location("langfuse_hook_lazy_import_probe", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_unconfigured_plugin_never_imports_langfuse(monkeypatch, tmp_path):
    # Before this change, the module imported langfuse and opentelemetry at load
    # time. Thus a plugin with no Langfuse keys also ran the slow import at each
    # hook run.
    module = _load_hook_module_without_forcing_import(monkeypatch, tmp_path)
    assert module.Langfuse is None

    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "CC_LANGFUSE_PUBLIC_KEY",
        "CC_LANGFUSE_SECRET_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(f"CLAUDE_PLUGIN_OPTION_{name}", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    assert module.main() == 0
    assert module.Langfuse is None


def test_missing_transcript_never_imports_langfuse(monkeypatch, tmp_path):
    module = _load_hook_module_without_forcing_import(monkeypatch, tmp_path)
    assert module.Langfuse is None

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    missing_transcript = tmp_path / "missing.jsonl"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sessionId": "s1", "transcriptPath": str(missing_transcript)})),
    )

    assert module.main() == 0
    assert module.Langfuse is None


def test_pending_work_starts_the_import_and_creates_a_client(hook_module, monkeypatch, tmp_path):
    # The counterpart of the skip tests: a run with work to do must start the
    # import and get a usable client. The hook_module fixture makes the stub
    # SDK importable; the probe module itself starts with Langfuse unset.
    module = _load_hook_module_without_forcing_import(monkeypatch, tmp_path)
    assert module.Langfuse is None

    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sessionId": "s1", "transcriptPath": str(transcript)})),
    )

    assert module.main() == 0
    assert module.Langfuse is not None


def test_caught_up_session_never_imports_langfuse(monkeypatch, tmp_path):
    module = _load_hook_module_without_forcing_import(monkeypatch, tmp_path)
    assert module.Langfuse is None

    state_dir = tmp_path / "claude-state"
    monkeypatch.setattr(module, "STATE_DIR", state_dir)
    monkeypatch.setattr(module, "STATE_FILE", state_dir / "langfuse_state.json")
    monkeypatch.setattr(module, "LOCK_FILE", state_dir / "langfuse_state.lock")
    monkeypatch.setattr(module, "LOG_FILE", state_dir / "langfuse_hook.log")

    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")

    state = module.load_hook_state()
    key = module.get_session_state_key("s1", str(transcript.resolve()))
    session_state = module.get_session_state(state, key)
    session_state.offset = transcript.stat().st_size
    module.save_session_state(state, key, session_state)

    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {"sessionId": "s1", "transcriptPath": str(transcript), "hookEventName": "SessionEnd"}
            )
        ),
    )

    assert module.main() == 0
    assert module.Langfuse is None
