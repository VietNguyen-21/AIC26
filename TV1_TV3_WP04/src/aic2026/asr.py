"""ASR and VAD adapters, original-timeline mapping, segment resume, and transcript
retrieval."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, Sequence

from .contracts import (
    ASRSegment,
    ASRSegmentManifest,
    ASRVideoMetrics,
    ASRWord,
    AudioRecord,
    MediaRecord,
    SearchCandidate,
    VADSegmentRecord,
)
from .ocr import normalize_search_text, strip_vietnamese_diacritics
from .text_index import TextDocument, search_text_index
from .utils import (
    read_json,
    read_jsonl,
    sha256_file,
    stable_json_hash,
    utcnow_iso,
    write_json,
    write_jsonl,
    write_parquet_optional,
)


# Segment and word timestamps are always converted back to the original video timeline.
class ASRRuntimeError(RuntimeError):
    """Raised when an explicitly requested ASR/VAD runtime is unavailable."""


class VADAdapter(Protocol):
    name: str
    version: str

    def detect(self, audio_path: str, config: Any) -> list[dict[str, Any]]: ...


class ASRAdapter(Protocol):
    name: str
    version: str

    def transcribe(self, audio_path: str, config: Any) -> list[dict[str, Any]]: ...

    def transcribe_batch(
        self, audio_paths: Sequence[str], config: Any
    ) -> list[list[dict[str, Any]]]: ...


class BaseVADAdapter:
    name = "base"
    version = "0"

    def detect(self, audio_path: str, config: Any) -> list[dict[str, Any]]:
        raise NotImplementedError


class BaseASRAdapter:
    name = "base"
    version = "0"

    def transcribe(self, audio_path: str, config: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    def transcribe_batch(
        self, audio_paths: Sequence[str], config: Any
    ) -> list[list[dict[str, Any]]]:
        # Adapters may override this with native batching.  The deterministic
        # default preserves compatibility while allowing the orchestrator to
        # enforce batch isolation, OOM retries and CPU fallback.
        return [self.transcribe(path, config) for path in audio_paths]


class NoVADAdapter(BaseVADAdapter):
    """Treat the whole WAV as speech; deterministic fallback for smoke tests."""

    name = "none"
    version = "1"

    def detect(self, audio_path: str, config: Any) -> list[dict[str, Any]]:
        duration_ms, _, _ = wav_info(audio_path)
        if duration_ms <= 0:
            return []
        return [{"start_ms": 0, "end_ms": duration_ms, "confidence": None}]


class SileroVADAdapter(BaseVADAdapter):
    name = "silero"

    def __init__(self):
        try:
            import silero_vad
            from silero_vad import get_speech_timestamps, load_silero_vad, read_audio
        except ImportError as exc:  # pragma: no cover - dependency-dependent
            raise ASRRuntimeError("Install silero-vad to use the Silero VAD adapter") from exc
        self._get_speech_timestamps = get_speech_timestamps
        self._read_audio = read_audio
        self._model = load_silero_vad()
        self.version = str(getattr(silero_vad, "__version__", "runtime"))

    def detect(self, audio_path: str, config: Any) -> list[dict[str, Any]]:
        wav = self._read_audio(audio_path, sampling_rate=16000)
        rows = self._get_speech_timestamps(
            wav,
            self._model,
            sampling_rate=16000,
            threshold=float(config.vad_threshold),
            min_speech_duration_ms=int(config.vad_min_speech_ms),
            min_silence_duration_ms=int(config.vad_min_silence_ms),
            speech_pad_ms=int(config.vad_speech_pad_ms),
            return_seconds=True,
        )
        return [
            {
                "start_ms": max(0, int(round(float(row["start"]) * 1000))),
                "end_ms": max(0, int(round(float(row["end"]) * 1000))),
                "confidence": None,
            }
            for row in rows
        ]


class ChunkFormerAdapter(BaseASRAdapter):
    """External ChunkFormer bridge; checkpoints remain outside source releases."""

    name = "chunkformer"

    def __init__(self, config: Any):
        checkpoint = Path(config.chunkformer_checkpoint_path or "")
        command = list(config.chunkformer_command or [])
        if not checkpoint.is_file():
            raise ASRRuntimeError(f"ChunkFormer checkpoint not found: {checkpoint}")
        if not command:
            raise ASRRuntimeError("chunkformer_command is required")
        self.checkpoint = checkpoint
        self.command = command
        self.timeout_seconds = int(config.chunkformer_timeout_seconds)
        self.version = sha256_file(checkpoint)[:16]

    def transcribe(self, audio_path: str, config: Any) -> list[dict[str, Any]]:
        output_path = Path(audio_path).with_suffix(Path(audio_path).suffix + ".asr-output.json")
        command = [
            part.format(
                audio=str(Path(audio_path).resolve()),
                output=str(output_path.resolve()),
                checkpoint=str(self.checkpoint.resolve()),
                device=str(config.device),
                language=str(config.language or ""),
                task=str(config.task),
            )
            for part in self.command
        ]
        try:
            subprocess.run(
                command,
                check=True,
                timeout=self.timeout_seconds,
                capture_output=True,
                text=True,
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ASRRuntimeError(f"ChunkFormer external command failed: {exc}") from exc
        finally:
            output_path.unlink(missing_ok=True)
        if not isinstance(payload, list):
            raise ASRRuntimeError("ChunkFormer output must be a JSON list")
        return [dict(item) for item in payload]


class NoOpASRAdapter(BaseASRAdapter):
    name = "noop"
    version = "1"

    def transcribe(self, audio_path: str, config: Any) -> list[dict[str, Any]]:
        return []


@dataclass(frozen=True)
class VADAdapterResolution:
    adapter: VADAdapter
    requested_adapter: str
    selected_adapter: str
    attempts: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class ASRAdapterResolution:
    adapter: ASRAdapter
    requested_adapter: str
    selected_adapter: str
    attempts: tuple[dict[str, str], ...] = ()


@dataclass
class ASRVideoResult:
    video_id: str
    segments: list[ASRSegment]
    vad_segments: list[VADSegmentRecord]
    processed_segments: int
    resumed_segments: int
    failed_segments: int
    status: str
    artifact_paths: list[Path] = field(default_factory=list)
    segment_errors: list[dict[str, Any]] = field(default_factory=list)


def resolve_device(requested: str) -> str:
    requested = requested.lower()
    if requested in {"cpu", "cuda"}:
        if requested == "cuda" and not _cuda_available():
            raise ASRRuntimeError("CUDA was explicitly requested but is not available")
        return requested
    return "cuda" if _cuda_available() else "cpu"



def make_vad_adapter(config: Any) -> VADAdapterResolution:
    """Resolve Silero VAD; ``none`` is retained only for deterministic fixtures."""

    requested = str(config.vad_adapter).lower()
    attempts: list[dict[str, str]] = []
    try:
        if requested == "silero":
            adapter: VADAdapter = SileroVADAdapter()
        elif requested == "none":
            adapter = NoVADAdapter()
        else:
            raise ASRRuntimeError(f"Unsupported VAD adapter: {requested}")
        return VADAdapterResolution(adapter, requested, requested, tuple(attempts))
    except Exception as exc:
        attempts.append({"adapter": requested, "error": f"{type(exc).__name__}: {exc}"})
        raise



def make_asr_adapter(config: Any) -> ASRAdapterResolution:
    """Resolve ChunkFormer explicitly; no legacy ASR fallback is allowed."""

    requested = str(config.adapter).lower()
    attempts: list[dict[str, str]] = []
    try:
        if requested == "chunkformer":
            adapter: ASRAdapter = ChunkFormerAdapter(config)
        elif requested == "noop":
            adapter = NoOpASRAdapter()
        else:
            raise ASRRuntimeError(f"Unsupported ASR adapter: {requested}")
        return ASRAdapterResolution(adapter, requested, requested, tuple(attempts))
    except Exception as exc:
        attempts.append({"adapter": requested, "error": f"{type(exc).__name__}: {exc}"})
        raise


def wav_info(audio_path: str | Path) -> tuple[int, int, int]:
    with wave.open(str(audio_path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        channels = handle.getnchannels()
    duration_ms = int(round(frames * 1000 / max(1, rate)))
    return duration_ms, rate, channels


def normalize_vad_intervals(
    raw_intervals: Sequence[dict[str, Any]],
    *,
    duration_ms: int,
    max_segment_ms: int,
    overlap_ms: int,
    merge_gap_ms: int,
) -> list[dict[str, Any]]:
    """Clamp, merge and split VAD intervals on the original audio timeline."""

    cleaned: list[dict[str, Any]] = []
    for row in raw_intervals:
        start = max(0, min(duration_ms, int(row.get("start_ms", 0))))
        end = max(0, min(duration_ms, int(row.get("end_ms", 0))))
        if end <= start:
            continue
        confidence = _probability_or_none(row.get("confidence"))
        cleaned.append({"start_ms": start, "end_ms": end, "confidence": confidence})
    cleaned.sort(key=lambda row: (row["start_ms"], row["end_ms"]))

    merged: list[dict[str, Any]] = []
    for row in cleaned:
        if merged and row["start_ms"] - merged[-1]["end_ms"] <= merge_gap_ms:
            merged[-1]["end_ms"] = max(merged[-1]["end_ms"], row["end_ms"])
            values = [v for v in (merged[-1].get("confidence"), row.get("confidence")) if v is not None]
            merged[-1]["confidence"] = sum(values) / len(values) if values else None
        else:
            merged.append(dict(row))

    chunks: list[dict[str, Any]] = []
    step = max_segment_ms - overlap_ms
    for row in merged:
        start = row["start_ms"]
        while start < row["end_ms"]:
            end = min(row["end_ms"], start + max_segment_ms)
            chunks.append({"start_ms": start, "end_ms": end, "confidence": row.get("confidence")})
            if end >= row["end_ms"]:
                break
            start += step
    return chunks


def write_wav_slice(
    source_path: str | Path,
    target_path: str | Path,
    start_ms: int,
    end_ms: int,
) -> Path:
    source = Path(source_path)
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "rb") as input_wav:
        params = input_wav.getparams()
        rate = input_wav.getframerate()
        start_frame = max(0, int(start_ms * rate / 1000))
        end_frame = min(input_wav.getnframes(), int(math.ceil(end_ms * rate / 1000)))
        input_wav.setpos(start_frame)
        frames = input_wav.readframes(max(0, end_frame - start_frame))
    temp = target.with_name(target.name + f".tmp-{os.getpid()}")
    with wave.open(str(temp), "wb") as output_wav:
        output_wav.setparams(params)
        output_wav.writeframes(frames)
    temp.replace(target)
    return target


def _vad_cache_path(run_root: Path, video_id: str) -> Path:
    return run_root / "asr" / "vad" / f"{video_id}.json"


def _segment_manifest_path(run_root: Path, video_id: str, vad_segment_id: str) -> Path:
    safe = vad_segment_id.replace(":", "_")
    return run_root / "asr" / "segments" / video_id / f"{safe}.json"


def _chunk_path(run_root: Path, video_id: str, vad_segment_id: str) -> Path:
    safe = vad_segment_id.replace(":", "_")
    return run_root / "asr" / "chunks" / video_id / f"{safe}.wav"


def _load_completed_segment(path: Path, fingerprint: str) -> ASRSegmentManifest | None:
    if not path.is_file():
        return None
    try:
        manifest = ASRSegmentManifest.model_validate(read_json(path))
    except Exception:
        return None
    if manifest.status != "completed" or manifest.fingerprint != fingerprint:
        return None
    return manifest


def _segment_fingerprint(
    *,
    audio_sha256: str,
    start_ms: int,
    end_ms: int,
    adapter: ASRAdapter,
    vad_adapter: VADAdapter,
    config: Any,
) -> str:
    return stable_json_hash(
        {
            "audio_sha256": audio_sha256,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "adapter": adapter.name,
            "adapter_version": adapter.version,
            "vad_adapter": vad_adapter.name,
            "vad_version": vad_adapter.version,
            "config": config.model_dump(mode="json") if hasattr(config, "model_dump") else dict(config),
        }
    )


def _normalize_adapter_segment(
    raw: dict[str, Any],
    *,
    run_id: str,
    video_id: str,
    vad_segment_id: str,
    offset_ms: int,
    chunk_end_ms: int,
    source_audio_sha256: str,
    adapter: ASRAdapter,
    index: int,
) -> ASRSegment | None:
    text = str(raw.get("text", "")).strip()
    if not text:
        return None
    start_ms = max(offset_ms, offset_ms + int(raw.get("start_ms", 0)))
    end_ms = min(chunk_end_ms, offset_ms + int(raw.get("end_ms", chunk_end_ms - offset_ms)))
    if end_ms < start_ms:
        end_ms = start_ms
    words: list[ASRWord] = []
    for word in raw.get("words", []) or []:
        word_start = max(start_ms, offset_ms + int(word.get("start_ms", 0)))
        word_end = min(end_ms, offset_ms + int(word.get("end_ms", 0)))
        if word_end < word_start:
            continue
        words.append(
            ASRWord(
                start_ms=word_start,
                end_ms=word_end,
                word=str(word.get("word", "")),
                probability=_probability_or_none(word.get("probability")),
            )
        )
    normalized = normalize_search_text(text)
    return ASRSegment(
        preprocess_run_id=run_id,
        segment_id=f"{vad_segment_id}:raw:{index:04d}",
        video_id=video_id,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        normalized_text=normalized,
        normalized_text_no_diacritics=normalize_search_text(strip_vietnamese_diacritics(text)),
        language=str(raw.get("language") or "unknown"),
        language_probability=_probability_or_none(raw.get("language_probability")),
        confidence=_probability_or_none(raw.get("confidence")),
        avg_logprob=_float_or_none(raw.get("avg_logprob")),
        no_speech_probability=_probability_or_none(raw.get("no_speech_probability")),
        words=words,
        vad_segment_id=vad_segment_id,
        source_audio_sha256=source_audio_sha256,
        model_name=adapter.name,
        model_version=adapter.version,
        created_at_utc=utcnow_iso(),
    )


def deduplicate_asr_segments(segments: Sequence[ASRSegment]) -> list[ASRSegment]:
    """Remove overlap duplicates while preserving distinct neighbouring speech."""

    ordered = sorted(segments, key=lambda row: (row.start_ms, row.end_ms, row.normalized_text))
    kept: list[ASRSegment] = []
    for row in ordered:
        duplicate_index: int | None = None
        for index in range(max(0, len(kept) - 4), len(kept)):
            existing = kept[index]
            if existing.video_id != row.video_id:
                continue
            if existing.normalized_text != row.normalized_text:
                continue
            overlap = max(0, min(existing.end_ms, row.end_ms) - max(existing.start_ms, row.start_ms))
            min_duration = max(1, min(existing.end_ms - existing.start_ms, row.end_ms - row.start_ms))
            if overlap / min_duration >= 0.5 or abs(existing.start_ms - row.start_ms) <= 500:
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(row)
            continue
        existing = kept[duplicate_index]
        existing_score = existing.avg_logprob if existing.avg_logprob is not None else -999.0
        row_score = row.avg_logprob if row.avg_logprob is not None else -999.0
        if row_score > existing_score or len(row.words) > len(existing.words):
            kept[duplicate_index] = row
    final: list[ASRSegment] = []
    for index, row in enumerate(sorted(kept, key=lambda item: (item.start_ms, item.end_ms))):
        final.append(row.model_copy(update={"segment_id": f"asr:{row.video_id}:{index:06d}"}))
    return final


def _is_cuda_oom(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".casefold()
    return any(
        token in text
        for token in [
            "cuda out of memory",
            "cuda error: out of memory",
            "cublas_status_alloc_failed",
            "outofmemoryerror",
        ]
    )


def _cpu_fallback_adapter(config: Any) -> ASRAdapterResolution:
    if not hasattr(config, "model_copy"):
        raise ASRRuntimeError("ASR config cannot create a CPU fallback copy")
    fallback_config = config.model_copy(
        update={
            "device": "cpu",
            "allow_cpu_fallback": False,
        }
    )
    return make_asr_adapter(fallback_config)


def run_asr_video(
    media: MediaRecord,
    audio: AudioRecord,
    run_root: str | Path,
    adapter: ASRAdapter,
    vad_adapter: VADAdapter,
    config: Any,
    *,
    asr_resolution: ASRAdapterResolution | None = None,
    vad_resolution: VADAdapterResolution | None = None,
) -> ASRVideoResult:
    """Run VAD and resumable ASR segments on the original video audio timeline."""
    root = Path(run_root)
    started = time.perf_counter()
    video_id = media.video_id
    requested_adapter = asr_resolution.requested_adapter if asr_resolution else adapter.name
    selected_adapter = asr_resolution.selected_adapter if asr_resolution else adapter.name
    requested_vad = vad_resolution.requested_adapter if vad_resolution else vad_adapter.name
    selected_vad = vad_resolution.selected_adapter if vad_resolution else vad_adapter.name

    if audio.status == "no_audio" or not audio.audio_path:
        metrics = ASRVideoMetrics(
            preprocess_run_id=media.preprocess_run_id,
            video_id=video_id,
            status="no_audio",
            requested_adapter=requested_adapter,
            selected_adapter=selected_adapter,
            requested_vad_adapter=requested_vad,
            selected_vad_adapter=selected_vad,
            adapter_name=adapter.name,
            adapter_version=adapter.version,
            vad_adapter_name=vad_adapter.name,
            vad_adapter_version=vad_adapter.version,
            audio_duration_ms=0,
            vad_segment_count=0,
            processed_segments=0,
            resumed_segments=0,
            failed_segments=0,
            transcript_segment_count=0,
            runtime_seconds=time.perf_counter() - started,
            initial_batch_size=max(1, int(config.batch_size)),
            final_batch_size=max(1, int(config.batch_size)),
            oom_retry_count=0,
            cpu_fallback_used=False,
            segments_per_second=0.0,
            audio_realtime_factor=0.0,
            created_at_utc=utcnow_iso(),
        )
        report_path = root / "reports" / "asr" / f"{video_id}.json"
        by_video_path = root / "asr" / "by_video" / f"{video_id}.jsonl"
        write_json(report_path, metrics.model_dump(mode="json"))
        write_jsonl(by_video_path, [])
        return ASRVideoResult(video_id, [], [], 0, 0, 0, "no_audio", [report_path, by_video_path])
    if audio.status != "ready":
        raise ASRRuntimeError(f"Audio is not ready for ASR: {video_id} ({audio.status})")

    audio_path = Path(audio.audio_path)
    if not audio_path.is_file():
        raise ASRRuntimeError(f"ASR audio file does not exist: {audio_path}")
    audio_sha256 = audio.audio_sha256 or sha256_file(audio_path)
    duration_ms, sample_rate, channels = wav_info(audio_path)
    if channels != 1:
        raise ASRRuntimeError("ASR expects mono audio from the preprocessing audio module")

    vad_fingerprint = stable_json_hash(
        {
            "audio_sha256": audio_sha256,
            "vad_adapter": vad_adapter.name,
            "vad_version": vad_adapter.version,
            "threshold": config.vad_threshold,
            "min_speech_ms": config.vad_min_speech_ms,
            "min_silence_ms": config.vad_min_silence_ms,
            "pad_ms": config.vad_speech_pad_ms,
            "max_segment_ms": config.segment_max_ms,
            "overlap_ms": config.segment_overlap_ms,
            "merge_gap_ms": config.segment_merge_gap_ms,
        }
    )
    vad_cache = _vad_cache_path(root, video_id)
    raw_vad: list[dict[str, Any]]
    cached = read_json(vad_cache) if vad_cache.is_file() else {}
    if cached.get("fingerprint") == vad_fingerprint and isinstance(cached.get("segments"), list):
        raw_vad = list(cached["segments"])
    else:
        raw_vad = vad_adapter.detect(str(audio_path), config)
        raw_vad = normalize_vad_intervals(
            raw_vad,
            duration_ms=duration_ms,
            max_segment_ms=int(config.segment_max_ms),
            overlap_ms=int(config.segment_overlap_ms),
            merge_gap_ms=int(config.segment_merge_gap_ms),
        )
        write_json(
            vad_cache,
            {
                "schema_version": "1.0.0",
                "preprocess_run_id": media.preprocess_run_id,
                "video_id": video_id,
                "fingerprint": vad_fingerprint,
                "adapter_name": vad_adapter.name,
                "adapter_version": vad_adapter.version,
                "audio_sha256": audio_sha256,
                "sample_rate_hz": sample_rate,
                "duration_ms": duration_ms,
                "segments": raw_vad,
                "created_at_utc": utcnow_iso(),
            },
        )

    vad_segments: list[VADSegmentRecord] = []
    all_segments: list[ASRSegment] = []
    processed = 0
    resumed = 0
    failed = 0
    errors: list[dict[str, Any]] = []
    artifact_paths: list[Path] = [vad_cache]
    pending: list[dict[str, Any]] = []

    for row in raw_vad:
        start_ms = int(row["start_ms"])
        end_ms = int(row["end_ms"])
        vad_segment_id = f"vad:{video_id}:{start_ms:010d}:{end_ms:010d}"
        vad_segments.append(
            VADSegmentRecord(
                preprocess_run_id=media.preprocess_run_id,
                vad_segment_id=vad_segment_id,
                video_id=video_id,
                start_ms=start_ms,
                end_ms=end_ms,
                vad_adapter=vad_adapter.name,
                confidence=_probability_or_none(row.get("confidence")),
                created_at_utc=utcnow_iso(),
            )
        )
        fingerprint = _segment_fingerprint(
            audio_sha256=audio_sha256,
            start_ms=start_ms,
            end_ms=end_ms,
            adapter=adapter,
            vad_adapter=vad_adapter,
            config=config,
        )
        manifest_path = _segment_manifest_path(root, video_id, vad_segment_id)
        completed = (
            _load_completed_segment(manifest_path, fingerprint)
            if config.segment_resume
            else None
        )
        if completed is not None:
            resumed += 1
            all_segments.extend(completed.transcript_segments)
            artifact_paths.append(manifest_path)
            continue
        pending.append(
            {
                "start_ms": start_ms,
                "end_ms": end_ms,
                "vad_segment_id": vad_segment_id,
                "fingerprint": fingerprint,
                "manifest_path": manifest_path,
                "chunk_path": _chunk_path(root, video_id, vad_segment_id),
            }
        )

    initial_batch_size = max(1, min(int(config.batch_size), len(pending) or 1))
    current_batch_size = initial_batch_size
    minimum_batch_size = max(1, int(config.min_batch_size))
    oom_retry_count = 0
    cpu_fallback_used = False
    active_adapter: ASRAdapter = adapter
    active_adapter_config = config
    queue = list(pending)

    while queue:
        batch = queue[:current_batch_size]
        for item in batch:
            write_wav_slice(
                audio_path,
                item["chunk_path"],
                int(item["start_ms"]),
                int(item["end_ms"]),
            )
        try:
            raw_batches = active_adapter.transcribe_batch(
                [str(item["chunk_path"]) for item in batch], active_adapter_config
            )
            if len(raw_batches) != len(batch):
                raise ASRRuntimeError(
                    "ASR adapter returned a different number of batch outputs"
                )
        except Exception as exc:
            for item in batch:
                item["chunk_path"].unlink(missing_ok=True)
            if _is_cuda_oom(exc):
                oom_retry_count += 1
                if oom_retry_count <= int(config.max_oom_retries) and current_batch_size > minimum_batch_size:
                    current_batch_size = max(minimum_batch_size, current_batch_size // 2)
                    continue
                if bool(config.allow_cpu_fallback) and not cpu_fallback_used:
                    fallback = _cpu_fallback_adapter(config)
                    active_adapter = fallback.adapter
                    active_adapter_config = config.model_copy(
                        update={
                            "device": "cpu",
                            "allow_cpu_fallback": False,
                        }
                    )
                    selected_adapter = f"{selected_adapter}->cpu:{fallback.selected_adapter}"
                    cpu_fallback_used = True
                    current_batch_size = max(1, minimum_batch_size)
                    continue
            if len(batch) > 1:
                # Isolate a non-OOM adapter failure to the smallest failing segment.
                current_batch_size = max(1, len(batch) // 2)
                continue

            item = batch[0]
            failed += 1
            error_text = f"{type(exc).__name__}: {exc}"
            errors.append(
                {
                    "vad_segment_id": item["vad_segment_id"],
                    "start_ms": item["start_ms"],
                    "end_ms": item["end_ms"],
                    "error": error_text,
                    "oom_retry_count": oom_retry_count,
                    "cpu_fallback_used": cpu_fallback_used,
                }
            )
            failed_manifest = ASRSegmentManifest(
                status="failed",
                preprocess_run_id=media.preprocess_run_id,
                video_id=video_id,
                vad_segment_id=item["vad_segment_id"],
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                fingerprint=item["fingerprint"],
                adapter_name=active_adapter.name,
                adapter_version=active_adapter.version,
                vad_adapter_name=vad_adapter.name,
                source_audio_sha256=audio_sha256,
                error=error_text,
                created_at_utc=utcnow_iso(),
            )
            write_json(
                item["manifest_path"], failed_manifest.model_dump(mode="json")
            )
            artifact_paths.append(item["manifest_path"])
            queue.pop(0)
            if bool(config.fail_fast):
                raise
            continue

        for item, raw_segments in zip(batch, raw_batches, strict=True):
            transcript_segments = [
                segment
                for item_index, raw in enumerate(raw_segments)
                if (
                    segment := _normalize_adapter_segment(
                        raw,
                        run_id=media.preprocess_run_id,
                        video_id=video_id,
                        vad_segment_id=item["vad_segment_id"],
                        offset_ms=item["start_ms"],
                        chunk_end_ms=item["end_ms"],
                        source_audio_sha256=audio_sha256,
                        adapter=active_adapter,
                        index=item_index,
                    )
                )
                is not None
            ]
            manifest = ASRSegmentManifest(
                status="completed",
                preprocess_run_id=media.preprocess_run_id,
                video_id=video_id,
                vad_segment_id=item["vad_segment_id"],
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                fingerprint=item["fingerprint"],
                adapter_name=active_adapter.name,
                adapter_version=active_adapter.version,
                vad_adapter_name=vad_adapter.name,
                source_audio_sha256=audio_sha256,
                transcript_segments=transcript_segments,
                created_at_utc=utcnow_iso(),
            )
            write_json(item["manifest_path"], manifest.model_dump(mode="json"))
            all_segments.extend(transcript_segments)
            processed += 1
            artifact_paths.append(item["manifest_path"])
            if bool(config.keep_chunk_audio):
                artifact_paths.append(item["chunk_path"])
            else:
                item["chunk_path"].unlink(missing_ok=True)
        del queue[: len(batch)]
        current_batch_size = min(initial_batch_size, max(1, len(queue))) if queue else current_batch_size

    final_segments = deduplicate_asr_segments(all_segments)
    by_video_path = root / "asr" / "by_video" / f"{video_id}.jsonl"
    by_video_parquet = root / "asr" / "by_video" / f"{video_id}.parquet"
    vad_jsonl = root / "asr" / "vad" / f"{video_id}.jsonl"
    payload = [row.model_dump(mode="json") for row in final_segments]
    vad_payload = [row.model_dump(mode="json") for row in vad_segments]
    write_jsonl(by_video_path, payload)
    write_parquet_optional(by_video_parquet, payload)
    write_jsonl(vad_jsonl, vad_payload)
    status = "partial" if failed else "completed"
    metrics = ASRVideoMetrics(
        preprocess_run_id=media.preprocess_run_id,
        video_id=video_id,
        status=status,
        requested_adapter=requested_adapter,
        selected_adapter=selected_adapter,
        requested_vad_adapter=requested_vad,
        selected_vad_adapter=selected_vad,
        adapter_name=adapter.name,
        adapter_version=adapter.version,
        vad_adapter_name=vad_adapter.name,
        vad_adapter_version=vad_adapter.version,
        audio_duration_ms=duration_ms,
        vad_segment_count=len(vad_segments),
        processed_segments=processed,
        resumed_segments=resumed,
        failed_segments=failed,
        transcript_segment_count=len(final_segments),
        detected_languages=sorted({row.language for row in final_segments if row.language}),
        runtime_seconds=(runtime_seconds := time.perf_counter() - started),
        initial_batch_size=initial_batch_size,
        final_batch_size=max(1, current_batch_size),
        oom_retry_count=oom_retry_count,
        cpu_fallback_used=cpu_fallback_used,
        segments_per_second=(processed / runtime_seconds if runtime_seconds > 0 else 0.0),
        audio_realtime_factor=(runtime_seconds / (duration_ms / 1000.0) if duration_ms > 0 else 0.0),
        segment_errors=errors,
        created_at_utc=utcnow_iso(),
    )
    report_path = root / "reports" / "asr" / f"{video_id}.json"
    write_json(report_path, metrics.model_dump(mode="json"))
    artifact_paths.extend([by_video_path, vad_jsonl, report_path])
    if by_video_parquet.is_file():
        artifact_paths.append(by_video_parquet)
    return ASRVideoResult(
        video_id=video_id,
        segments=final_segments,
        vad_segments=vad_segments,
        processed_segments=processed,
        resumed_segments=resumed,
        failed_segments=failed,
        status=status,
        artifact_paths=sorted(set(artifact_paths)),
        segment_errors=errors,
    )


def load_asr_video_result(run_root: str | Path, video_id: str) -> ASRVideoResult | None:
    root = Path(run_root)
    report_path = root / "reports" / "asr" / f"{video_id}.json"
    by_video_path = root / "asr" / "by_video" / f"{video_id}.jsonl"
    vad_path = root / "asr" / "vad" / f"{video_id}.jsonl"
    if not report_path.is_file() or not by_video_path.is_file():
        return None
    report = ASRVideoMetrics.model_validate(read_json(report_path))
    segments = [ASRSegment.model_validate(row) for row in read_jsonl(by_video_path)]
    vad_segments = [VADSegmentRecord.model_validate(row) for row in read_jsonl(vad_path)]
    artifacts = [report_path, by_video_path]
    if vad_path.is_file():
        artifacts.append(vad_path)
    parquet = by_video_path.with_suffix(".parquet")
    if parquet.is_file():
        artifacts.append(parquet)
    return ASRVideoResult(
        video_id=video_id,
        segments=segments,
        vad_segments=vad_segments,
        processed_segments=report.processed_segments,
        resumed_segments=report.resumed_segments,
        failed_segments=report.failed_segments,
        status=report.status,
        artifact_paths=artifacts,
        segment_errors=report.segment_errors,
    )


def cleanup_asr_video(run_root: str | Path, video_id: str, *, preserve_segment_cache: bool) -> None:
    root = Path(run_root)
    for path in [
        root / "asr" / "by_video" / f"{video_id}.jsonl",
        root / "asr" / "by_video" / f"{video_id}.parquet",
        root / "asr" / "vad" / f"{video_id}.jsonl",
        root / "reports" / "asr" / f"{video_id}.json",
    ]:
        path.unlink(missing_ok=True)
    if not preserve_segment_cache:
        shutil.rmtree(root / "asr" / "segments" / video_id, ignore_errors=True)
        shutil.rmtree(root / "asr" / "chunks" / video_id, ignore_errors=True)
        (root / "asr" / "vad" / f"{video_id}.json").unlink(missing_ok=True)


def consolidate_asr_artifacts(
    run_root: str | Path,
    video_ids: Sequence[str] | None = None,
) -> list[ASRSegment]:
    root = Path(run_root)
    allowed = set(video_ids) if video_ids is not None else None
    segments: list[ASRSegment] = []
    for path in sorted((root / "asr" / "by_video").glob("*.jsonl")):
        if allowed is not None and path.stem not in allowed:
            path.unlink(missing_ok=True)
            path.with_suffix(".parquet").unlink(missing_ok=True)
            (root / "asr" / "vad" / f"{path.stem}.jsonl").unlink(missing_ok=True)
            (root / "asr" / "vad" / f"{path.stem}.json").unlink(missing_ok=True)
            (root / "reports" / "asr" / f"{path.stem}.json").unlink(missing_ok=True)
            shutil.rmtree(root / "asr" / "segments" / path.stem, ignore_errors=True)
            shutil.rmtree(root / "asr" / "chunks" / path.stem, ignore_errors=True)
            continue
        segments.extend(ASRSegment.model_validate(row) for row in read_jsonl(path))
    segments = sorted(segments, key=lambda row: (row.video_id, row.start_ms, row.end_ms, row.segment_id))
    payload = [row.model_dump(mode="json") for row in segments]
    write_jsonl(root / "asr" / "asr.jsonl", payload)
    write_parquet_optional(root / "asr" / "asr.parquet", payload)

    reports = []
    for path in sorted((root / "reports" / "asr").glob("*.json")):
        if allowed is not None and path.stem not in allowed:
            path.unlink(missing_ok=True)
            continue
        try:
            reports.append(ASRVideoMetrics.model_validate(read_json(path)))
        except Exception:
            continue
    summary = {
        "schema_version": "1.0.0",
        "video_count": len(reports),
        "completed_videos": sum(row.status == "completed" for row in reports),
        "partial_videos": sum(row.status == "partial" for row in reports),
        "no_audio_videos": sum(row.status == "no_audio" for row in reports),
        "failed_videos": sum(row.status == "failed" for row in reports),
        "vad_segment_count": sum(row.vad_segment_count for row in reports),
        "transcript_segment_count": len(segments),
        "processed_segments": sum(row.processed_segments for row in reports),
        "resumed_segments": sum(row.resumed_segments for row in reports),
        "failed_segments": sum(row.failed_segments for row in reports),
        "created_at_utc": utcnow_iso(),
    }
    write_json(root / "reports" / "asr_summary.json", summary)
    return segments


def clear_consolidated_asr_artifacts(run_root: str | Path) -> None:
    root = Path(run_root)
    write_jsonl(root / "asr" / "asr.jsonl", [])
    (root / "asr" / "asr.parquet").unlink(missing_ok=True)
    write_json(
        root / "reports" / "asr_summary.json",
        {
            "schema_version": "1.0.0",
            "video_count": 0,
            "completed_videos": 0,
            "partial_videos": 0,
            "no_audio_videos": 0,
            "failed_videos": 0,
            "vad_segment_count": 0,
            "transcript_segment_count": 0,
            "processed_segments": 0,
            "resumed_segments": 0,
            "failed_segments": 0,
            "status": "disabled_or_unavailable",
            "created_at_utc": utcnow_iso(),
        },
    )


def build_asr_documents(run_root: str | Path) -> list[TextDocument]:
    documents: list[TextDocument] = []
    for row in read_jsonl(Path(run_root) / "asr" / "asr.jsonl"):
        text = " ".join(
            value
            for value in [
                str(row.get("normalized_text", "")),
                str(row.get("normalized_text_no_diacritics", "")),
            ]
            if value
        )
        documents.append(TextDocument(str(row["segment_id"]), text, {**row, "source": "asr"}))
    return documents


def asr_search(
    query_id: str,
    query: str,
    run_id: str,
    run_root: str | Path,
    k: int = 100,
    *,
    settings: Any | None = None,
) -> list[SearchCandidate]:
    """Search persistent ASR evidence while preserving transcript intervals and provenance."""
    return search_text_index(
        query_id,
        query,
        run_id,
        run_root,
        k,
        settings=settings,
        source_filter={"asr"},
    )


def _cuda_available() -> bool:
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _probability_or_none(value: Any) -> float | None:
    number = _float_or_none(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))
