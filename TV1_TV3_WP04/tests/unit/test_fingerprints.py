from pathlib import Path

from aic2026.config import Settings
from aic2026.fingerprints import build_module_fingerprint, module_model_identity


def fp(module, settings, source="a" * 64, deps=None):
    return build_module_fingerprint(
        module,
        source_sha256=source,
        settings=settings,
        pipeline_version="0.14.1+tv1.1",
        dependency_fingerprints=deps or {},
    )


def test_audio_change_only_invalidates_audio_branch():
    base = Settings()
    changed = Settings()
    changed.media.audio_sample_rate_hz = 22050
    assert fp("audio", base) != fp("audio", changed)
    assert fp("frame_index", base) == fp("frame_index", changed)
    assert fp("keyframes", base) == fp("keyframes", changed)


def test_keyframe_change_invalidates_keyframes_not_frame_index():
    base = Settings()
    changed = Settings()
    changed.keyframes.max_gap_ms = 6000
    assert fp("keyframes", base) != fp("keyframes", changed)
    assert fp("frame_index", base) == fp("frame_index", changed)


def test_dependency_fingerprint_propagates_to_temporal():
    settings = Settings()
    assert fp("temporal", settings, deps={"keyframes": "x"}) != fp(
        "temporal", settings, deps={"keyframes": "y"}
    )


def test_checkpoint_replacement_at_same_path_changes_identity(tmp_path: Path):
    checkpoint = tmp_path / "model.pth"
    checkpoint.write_bytes(b"first")
    settings = Settings()
    settings.keyframes.autoshoot_checkpoint_path = checkpoint
    first = module_model_identity("keyframes", settings)
    checkpoint.write_bytes(b"second")
    second = module_model_identity("keyframes", settings)
    assert first["autoshoot_checkpoint_sha256"] != second["autoshoot_checkpoint_sha256"]
