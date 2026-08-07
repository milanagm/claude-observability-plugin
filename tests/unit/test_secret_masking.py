from __future__ import annotations

import hashlib


def test_masks_langfuse_key_patterns_in_strings(hook_module):
    masked = hook_module.mask_secret_text("keys: sk-lf-abc123 and pk-lf-def_456")
    assert masked == "keys: [LANGFUSE_KEY_REDACTED] and [LANGFUSE_KEY_REDACTED]"


def test_masks_configured_literal_secrets(hook_module):
    hook_module.set_mask_literals(["super-secret-value", None])
    try:
        masked = hook_module.mask_secret_text("token=super-secret-value rest")
        assert masked == "token=[LANGFUSE_KEY_REDACTED] rest"
    finally:
        hook_module.set_mask_literals([])


def test_mask_secrets_recurses_through_dicts_and_lists(hook_module):
    masked = hook_module.mask_secrets({"a": ["sk-lf-x1"], "b": {"c": "pk-lf-y2"}, "n": 42})
    assert masked == {"a": ["[LANGFUSE_KEY_REDACTED]"], "b": {"c": "[LANGFUSE_KEY_REDACTED]"}, "n": 42}


def test_mask_secrets_survives_circular_structures(hook_module):
    obj = {"name": "sk-lf-zzz"}
    obj["self"] = obj
    masked = hook_module.mask_secrets(obj)
    assert masked["name"] == "[LANGFUSE_KEY_REDACTED]"
    assert masked["self"] == "[circular]"


def test_mask_secrets_allows_shared_objects_in_two_branches(hook_module):
    shared = {"v": "ok"}
    masked = hook_module.mask_secrets({"a": shared, "b": shared})
    assert masked == {"a": {"v": "ok"}, "b": {"v": "ok"}}


def test_truncate_text_masks_before_truncation_and_hashing(hook_module):
    # Key sits right at the truncation boundary: without mask-before-truncate,
    # a fragment of it would survive in the kept head.
    text = "x" * 19_990 + " sk-lf-secretsecretsecret " + "y" * 6_000
    kept, meta = hook_module.truncate_text(text, 20_000)
    assert "sk-lf-" not in kept
    assert meta["truncated"] is True
    # The recorded hash fingerprints the masked text, not secret-bearing content.
    masked_full = hook_module.mask_secret_text(text)
    assert meta["sha256"] == hashlib.sha256(masked_full.encode("utf-8")).hexdigest()


def test_truncate_text_unchanged_for_innocent_text(hook_module):
    kept, meta = hook_module.truncate_text("hello world")
    assert kept == "hello world"
    assert meta == {"truncated": False, "orig_len": 11}


def test_tool_input_dicts_are_masked(hook_module):
    tool_use = {"input": {"command": "echo sk-lf-abc", "nested": ["pk-lf-def"]}}
    value, meta = hook_module.get_tool_input_for_observation(tool_use)
    assert value == {"command": "echo [LANGFUSE_KEY_REDACTED]", "nested": ["[LANGFUSE_KEY_REDACTED]"]}
    assert meta is None


def test_config_load_registers_literals(hook_module, monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-unusual-format-public")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-unusual-format-secret")
    try:
        config = hook_module.get_langfuse_config()
        assert config is not None
        # Literal masking works even for keys that don't match the pattern.
        masked = hook_module.mask_secret_text("found sk-unusual-format-secret in .env")
        assert masked == "found [LANGFUSE_KEY_REDACTED] in .env"
    finally:
        hook_module.set_mask_literals([])
