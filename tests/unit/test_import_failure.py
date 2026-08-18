from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_import_failure_logs_and_fails_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Exec the hook as a fresh module: the autouse isolation fixture patches the
    # session module's constants, so home must be redirected for this re-import.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setitem(sys.modules, "langfuse", None)

    spec = importlib.util.spec_from_file_location(
        "langfuse_hook_import_probe", REPO_ROOT / "hooks" / "langfuse_hook.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)

    # The hook module starts the SDK import later. Therefore the module must load
    # without an error when langfuse is not available. The failure occurs when
    # the module first uses the SDK.
    spec.loader.exec_module(module)

    assert module._ensure_langfuse_imported() is False
    assert module.Langfuse is None

    log_text = (tmp_path / ".claude" / "state" / "langfuse_hook.log").read_text(encoding="utf-8")
    assert "langfuse import failed" in log_text
    assert sys.version.split()[0] in log_text
    assert sys.executable in log_text
    assert "PATH=" in log_text
    assert "Hint: uv was not found on this PATH" in log_text

    # The old module-level guard gave a contract: the hook always exits with code
    # 0. This contract must stay. A full main() run returns 0 when the SDK is not
    # available and the session has work to do.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"type": "user"}\n', encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(json.dumps({"sessionId": "s1", "transcriptPath": str(transcript)})),
    )

    assert module.main() == 0
    assert module.Langfuse is None
