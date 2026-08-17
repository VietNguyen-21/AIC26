"""Adapters for approved local model commands without embedding vendor model source."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from .adapters import ASRRawSegment, AdapterUnavailableError, OCRRawDetection, ObjectRawDetection
from .contracts import AudioRecord, FrameRecord


@dataclass(slots=True)
class _CommandAdapter:
    command_env: str
    model_name: str
    model_version: str = "local"
    vad_version: str = "local"

    def _run(self, **values: str) -> Any:
        command = os.environ.get(self.command_env, "").strip()
        if not command:
            raise AdapterUnavailableError(f"local model command is not configured: {self.command_env}")
        try:
            completed = subprocess.run(
                command.format(**values), shell=True, check=True, capture_output=True, text=True,
            )
            return json.loads(completed.stdout)
        except subprocess.CalledProcessError as error:
            raise AdapterUnavailableError(f"local model command failed ({self.command_env}): {error.stderr.strip()}") from error
        except json.JSONDecodeError as error:
            raise AdapterUnavailableError(f"local model command must emit JSON ({self.command_env})") from error


class CommandOCRAdapter(_CommandAdapter):
    def detect(self, frame: FrameRecord) -> list[OCRRawDetection]:
        if not frame.keyframe_path:
            raise AdapterUnavailableError("OCR requires FrameRecord.keyframe_path")
        output = self._run(keyframe_path=frame.keyframe_path)
        rows = output.get("detections", output) if isinstance(output, dict) else output
        if not isinstance(rows, list):
            raise AdapterUnavailableError("OCR command JSON must be a list or {detections: [...]}")
        return [OCRRawDetection(str(row["text"]), tuple(row["bbox_xyxy_norm"]), float(row["confidence"])) for row in rows]


class CommandASRAdapter(_CommandAdapter):
    def transcribe(self, audio: AudioRecord) -> list[ASRRawSegment]:
        if not audio.audio_path:
            raise AdapterUnavailableError("ASR requires AudioRecord.audio_path")
        output = self._run(audio_path=audio.audio_path)
        rows = output.get("segments", output) if isinstance(output, dict) else output
        if not isinstance(rows, list):
            raise AdapterUnavailableError("ASR command JSON must be a list or {segments: [...]}")
        return [ASRRawSegment(int(row["start_ms"]), int(row["end_ms"]), str(row["text"]), float(row["confidence"])) for row in rows]


class CommandObjectAdapter(_CommandAdapter):
    def detect(self, frame: FrameRecord) -> list[ObjectRawDetection]:
        if not frame.keyframe_path:
            raise AdapterUnavailableError("object detection requires FrameRecord.keyframe_path")
        output = self._run(keyframe_path=frame.keyframe_path)
        rows = output.get("detections", output) if isinstance(output, dict) else output
        if not isinstance(rows, list):
            raise AdapterUnavailableError("object command JSON must be a list or {detections: [...]}")
        return [ObjectRawDetection(str(row["label"]), tuple(row["bbox_xyxy_norm"]), float(row["confidence"])) for row in rows]


def build_ocr_adapter(command_env: str = "WP04_DEEPSOLO_COMMAND", model_version: str = "local") -> CommandOCRAdapter:
    return CommandOCRAdapter(command_env, "deepsolo-parseq-vn", model_version)


def build_asr_adapter(command_env: str = "WP04_CHUNKFORMER_COMMAND", model_version: str = "local", vad_version: str = "local") -> CommandASRAdapter:
    return CommandASRAdapter(command_env, "chunkformer-ctc-large-vie", model_version, vad_version)


def build_object_adapter(command_env: str = "WP04_RFDETR_COMMAND", model_version: str = "local") -> CommandObjectAdapter:
    return CommandObjectAdapter(command_env, "rf-detr", model_version)
