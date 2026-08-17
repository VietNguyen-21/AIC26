from __future__ import annotations

from pathlib import Path

from aic2026.config import Settings
from aic2026.contracts import (
    AudioRecord,
    FrameRecord,
    MediaRecord,
    OriginalFrameIndexRecord,
    TemporalFrameRecord,
)
from aic2026.preprocessing import run_preprocessing
from aic2026.registry import RunRegistry
from aic2026.utils import utcnow_iso, write_json, write_jsonl


def test_interrupted_keyframes_resume_without_repeating_completed_modules(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    source.mkdir()
    video = source / "V001.mp4"
    video.write_bytes(b"not-a-real-video-but-ingest-only-needs-bytes")
    runs_root = tmp_path / "runs"
    settings = Settings()
    settings.paths.runs_root = runs_root
    settings.media.allow_ffmpeg_decode_fallback = True
    raw = settings.model_dump(mode="json")
    calls = {"probe": 0, "index": 0, "decode": 0, "audio": 0, "keyframes": 0}

    def fake_probe(record, run_id, timeout):
        calls["probe"] += 1
        return MediaRecord(
            preprocess_run_id=run_id,
            video_id=record.video_id,
            original_video_path=record.original_video_path,
            source_sha256=record.source_sha256,
            time_base="1/1000",
            fps_nominal=25.0,
            fps_average=25.0,
            is_variable_frame_rate=False,
            frame_count=3,
            duration_ms=80,
            width_px=16,
            height_px=16,
            codec="fake",
            has_audio=True,
            created_at_utc=utcnow_iso(),
        )

    def fake_ensure(media, run_root, backend, timeout):
        calls["index"] += 1
        path = Path(run_root) / "frame_indexes" / f"{media.video_id}.jsonl"
        rows = [
            OriginalFrameIndexRecord(
                preprocess_run_id=media.preprocess_run_id,
                video_id=media.video_id,
                frame_id=index,
                decode_index=index,
                pts=index * 40,
                dts=index * 40,
                time_base="1/1000",
                timestamp_ms=index * 40,
                is_technical_keyframe=index == 0,
                created_at_utc=utcnow_iso(),
            )
            for index in range(3)
        ]
        write_jsonl(path, rows)
        write_json(
            Path(run_root) / "frame_indexes" / f"{media.video_id}.manifest.json",
            {"video_id": media.video_id, "frame_count": 3},
        )
        media.original_frame_index_path = str(path)
        media.frame_index_backend = "ffprobe"
        media.frame_count = 3
        return path

    def fake_decode(*args, **kwargs):
        calls["decode"] += 1
        return [{"frame_id": 1, "timestamp_ms": 40, "decoded": True}]

    def fake_audio(media, output_dir, sample_rate):
        calls["audio"] += 1
        path = Path(output_dir) / f"{media.video_id}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"wav")
        return AudioRecord(
            preprocess_run_id=media.preprocess_run_id,
            video_id=media.video_id,
            audio_path=str(path),
            audio_sha256="f" * 64,
            sample_rate_hz=sample_rate,
            channels=1,
            duration_ms=media.duration_ms,
            status="ready",
            created_at_utc=utcnow_iso(),
        )

    def failing_keyframes(*args, **kwargs):
        calls["keyframes"] += 1
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr("aic2026.preprocessing.probe_media", fake_probe)
    monkeypatch.setattr("aic2026.preprocessing.ensure_original_frame_index", fake_ensure)
    monkeypatch.setattr("aic2026.preprocessing.decode_probe", fake_decode)
    monkeypatch.setattr("aic2026.preprocessing.extract_audio", fake_audio)
    monkeypatch.setattr("aic2026.preprocessing.extract_keyframes", failing_keyframes)

    first = run_preprocessing(
        source=source,
        run_id="resume-v1",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert first.run.status == "partial"
    assert any(row["module"] == "keyframes" for row in first.errors)
    assert calls == {"probe": 1, "index": 1, "decode": 1, "audio": 1, "keyframes": 1}

    def should_not_repeat(*args, **kwargs):
        raise AssertionError("completed module was unexpectedly recomputed")

    def successful_keyframes(media, run_root, settings):
        calls["keyframes"] += 1
        keyframe = Path(run_root) / "keyframes" / media.video_id / "000000.jpg"
        thumbnail = Path(run_root) / "thumbnails" / media.video_id / "000000.jpg"
        keyframe.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.parent.mkdir(parents=True, exist_ok=True)
        keyframe.write_bytes(b"jpg")
        thumbnail.write_bytes(b"jpg")
        frame = FrameRecord(
            preprocess_run_id=media.preprocess_run_id,
            video_id=media.video_id,
            frame_id=1,
            keyframe_seq=0,
            timestamp_ms=40,
            pts=40,
            time_base="1/1000",
            decode_index=1,
            shot_id=f"{media.video_id}:shot:000000",
            keyframe_path=str(keyframe),
            thumbnail_path=str(thumbnail),
            selection_reason="shot_representative",
            created_at_utc=utcnow_iso(),
        )
        write_jsonl(Path(run_root) / "mappings" / f"{media.video_id}.jsonl", [frame])
        write_jsonl(Path(run_root) / "shots" / f"{media.video_id}.jsonl", [])
        write_json(
            Path(run_root) / "reports" / "keyframes" / f"{media.video_id}.json",
            {"video_id": media.video_id, "keyframe_count": 1},
        )
        return [frame]

    def fake_temporal(frames, run_root, **kwargs):
        frame = frames[0]
        row = TemporalFrameRecord(
            preprocess_run_id=frame.preprocess_run_id,
            video_id=frame.video_id,
            frame_id=frame.frame_id,
            keyframe_seq=frame.keyframe_seq,
            timestamp_ms=frame.timestamp_ms,
            pts=frame.pts,
            time_base=frame.time_base,
            shot_id=frame.shot_id,
            created_at_utc=utcnow_iso(),
        )
        root = Path(run_root) / "temporal"
        write_jsonl(root / "temporal_frames.jsonl", [row])
        write_jsonl(root / "shots.jsonl", [])
        write_jsonl(root / "asr_links.jsonl", [])
        write_json(root / "manifest.json", {"temporal_frame_count": 1})
        return [row]

    monkeypatch.setattr("aic2026.preprocessing.probe_media", should_not_repeat)
    monkeypatch.setattr(
        "aic2026.preprocessing.ensure_original_frame_index", should_not_repeat
    )
    monkeypatch.setattr("aic2026.preprocessing.decode_probe", should_not_repeat)
    monkeypatch.setattr("aic2026.preprocessing.extract_audio", should_not_repeat)
    monkeypatch.setattr("aic2026.preprocessing.extract_keyframes", successful_keyframes)
    monkeypatch.setattr("aic2026.preprocessing.build_temporal_registry", fake_temporal)

    second = run_preprocessing(
        source=source,
        run_id="resume-v1",
        settings=settings,
        raw_config=raw,
        repository_root=tmp_path,
    )
    assert second.run.status == "completed"
    assert second.errors == []
    assert calls == {"probe": 1, "index": 1, "decode": 1, "audio": 1, "keyframes": 2}

    run_root = runs_root / "resume-v1"
    with RunRegistry(run_root / "registry" / "run_registry.sqlite3") as registry:
        statuses = {
            row["module"]: row for row in registry.list_status("resume-v1")
        }
    assert statuses["media_probe"]["attempt_count"] == 1
    assert statuses["frame_index"]["attempt_count"] == 1
    assert statuses["audio"]["attempt_count"] == 1
    assert statuses["keyframes"]["attempt_count"] == 2
    assert statuses["keyframes"]["status"] == "completed"
