import json
from pathlib import Path

from wp04.cli import build_preprocess_fingerprint, main
from wp04.contracts import AudioRecord, FrameRecord, OCRDetection, WP04RunIdentity
from wp04.storage import ArtifactStore


def test_cli_search_emits_tv4_candidate_json(tmp_path: Path, capsys):
    store = ArtifactStore(tmp_path, WP04RunIdentity("tv1", "wp04", "inputs", "config"))
    ocr = OCRDetection("tv1", "v", 42, 1400, "BÁNH MÌ", "bánh mì", (0.1, 0.2, 0.3, 0.4), 0.9, "m", "v", "ocr:v:42:0")
    store.commit_video("ocr", "v", [ocr], "fp")
    assert main([
        "search", "--run-dir", str(tmp_path), "--preprocess-run-id", "tv1", "--artifact-set-id", "wp04",
        "--source", "ocr", "--query", "banh mi",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["candidates"][0]["source"] == "ocr"


def test_cli_validate_writes_and_emits_promotion_gate(tmp_path: Path, capsys):
    frames = tmp_path / "frames.json"
    frames.write_text(json.dumps([{
        "preprocess_run_id": "tv1", "video_id": "v", "frame_id": 42, "keyframe_seq": 1, "timestamp_ms": 1400,
        "keyframe_path": "keyframes/v/000042.jpg", "keyframe_sha256": "frame-sha",
    }]), encoding="utf-8")
    assert main([
        "validate", "--run-dir", str(tmp_path), "--preprocess-run-id", "tv1", "--artifact-set-id", "wp04",
        "--frames-json", str(frames),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_cli_preprocess_surfaces_unconfigured_models_but_keeps_no_audio_valid(tmp_path: Path, capsys):
    frames = tmp_path / "frames.json"
    frames.write_text(json.dumps([{
        "preprocess_run_id": "tv1", "video_id": "v", "frame_id": 42, "keyframe_seq": 1, "timestamp_ms": 1400,
        "keyframe_path": "keyframes/v/000042.jpg", "keyframe_sha256": "frame-sha",
    }]), encoding="utf-8")
    audio = tmp_path / "audio.json"
    audio.write_text(json.dumps([{
        "preprocess_run_id": "tv1", "video_id": "v", "audio_path": None, "checksum": None,
        "declared_present": False, "duration_ms": None,
    }]), encoding="utf-8")
    config = Path(__file__).parents[1] / "configs" / "default.yaml"
    assert main([
        "preprocess", "--run-dir", str(tmp_path), "--preprocess-run-id", "tv1", "--artifact-set-id", "wp04",
        "--frames-json", str(frames), "--audio-json", str(audio), "--config", str(config),
    ]) == 0
    states = {item["modality"]: item["state"] for item in json.loads(capsys.readouterr().out)["statuses"]}
    assert states == {"ocr": "failed", "asr": "no_audio", "object": "failed", "metadata": "ready"}


def test_preprocess_fingerprint_changes_with_keyframe_bytes():
    audio = AudioRecord("tv1", "v", None, None, False, None)
    first = FrameRecord("tv1", "v", 42, 1, 1400, "keyframes/42.jpg", "first")
    second = FrameRecord("tv1", "v", 42, 1, 1400, "keyframes/42.jpg", "second")
    config = {"normalization_version": "v", "modalities": {}}
    assert build_preprocess_fingerprint([first], {"v": audio}, config) != build_preprocess_fingerprint([second], {"v": audio}, config)
