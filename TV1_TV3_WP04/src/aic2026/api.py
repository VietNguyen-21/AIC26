"""Read-only FastAPI service for TV1 preprocessing and TV3 evidence artifacts."""

from __future__ import annotations

import mimetypes
from contextlib import asynccontextmanager
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Iterator

import cv2
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import __version__
from .config import Settings, load_settings
from .evidence_catalog import (
    CatalogPage,
    EvidenceCatalog,
    EvidenceCatalogError,
    validate_evidence_catalog,
)
from .contracts import (
    ASRSegment,
    FrameRecord,
    MediaRecord,
    MetadataRecord,
    ObjectDetection,
    OCRDetection,
    SearchRequest,
)
from .media import FrameResolver
from .registry import RunRegistry
from .asr import asr_search
from .metadata import metadata_search
from .modalities import text_search
from .objects import object_search
from .ocr import ocr_search
from .text_index import invalidate_text_index_cache, validate_text_index_artifacts
from .temporal import TemporalRegistry
from .utils import ensure_relative_to, read_json, read_jsonl


class RunActivationResponse(BaseModel):
    active_run_id: str
    status: str


def _parse_byte_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse one RFC 7233 byte range and return inclusive bounds."""

    if file_size <= 0 or not range_header.startswith("bytes="):
        raise ValueError("invalid byte range")
    value = range_header[6:].strip()
    if "," in value or "-" not in value:
        raise ValueError("only one byte range is supported")
    left, right = value.split("-", 1)
    if not left:
        suffix = int(right)
        if suffix <= 0:
            raise ValueError("invalid suffix range")
        start = max(0, file_size - suffix)
        return start, file_size - 1
    start = int(left)
    end = int(right) if right else file_size - 1
    if start < 0 or start >= file_size or end < start:
        raise ValueError("range is outside the file")
    return start, min(end, file_size - 1)


def _iter_file_range(path: Path, start: int, end: int, chunk_size: int) -> Iterator[bytes]:
    remaining = end - start + 1
    with path.open("rb") as handle:
        handle.seek(start)
        while remaining > 0:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


class PreprocessingService:
    def __init__(self, run_id: str, settings: Settings):
        self.settings = settings
        self._lock = RLock()
        self._resolver_cache: OrderedDict[str, FrameResolver] = OrderedDict()
        self.active_run_id = ""
        self.run_root = Path()
        self.media: dict[str, MediaRecord] = {}
        self.frames: dict[str, list[FrameRecord]] = {}
        self.temporal: TemporalRegistry | None = None
        self.catalog: EvidenceCatalog | None = None
        self.activate(run_id)

    def close(self) -> None:
        with self._lock:
            for resolver in self._resolver_cache.values():
                resolver.close()
            self._resolver_cache.clear()

    def activate(self, run_id: str) -> str:
        if not run_id or Path(run_id).name != run_id or any(ch in run_id for ch in "/\\"):
            raise ValueError("invalid run_id")
        root = Path(self.settings.paths.runs_root) / run_id
        if not root.is_dir():
            raise FileNotFoundError(root)
        media_rows = [
            MediaRecord.model_validate(row)
            for row in read_jsonl(root / "media" / "media.jsonl")
        ]
        frames = [
            FrameRecord.model_validate(row) for row in read_jsonl(root / "frames.jsonl")
        ]
        grouped: dict[str, list[FrameRecord]] = {}
        for frame in frames:
            grouped.setdefault(frame.video_id, []).append(frame)
        temporal = TemporalRegistry.from_run_root(root) if (root / "temporal" / "manifest.json").is_file() else None
        catalog = (
            EvidenceCatalog(root, maximum_page_size=self.settings.evidence_catalog.maximum_page_size)
            if (root / "evidence_catalog" / "manifest.json").is_file()
            else None
        )
        with self._lock:
            self.close()
            self.active_run_id = run_id
            self.run_root = root
            self.media = {row.video_id: row for row in media_rows}
            self.frames = grouped
            self.temporal = temporal
            self.catalog = catalog
        status = "degraded" if not self.media or temporal is None else "ready"
        return status

    def resolver(self, video_id: str) -> FrameResolver:
        with self._lock:
            resolver = self._resolver_cache.get(video_id)
            if resolver is not None:
                self._resolver_cache.move_to_end(video_id)
                return resolver
            media = self.media.get(video_id)
            if media is None:
                raise KeyError(video_id)
            resolver = FrameResolver(
                media,
                frame_index_path=media.original_frame_index_path,
                backend="auto",
                allow_ffmpeg_fallback=self.settings.media.allow_ffmpeg_decode_fallback,
            )
            self._resolver_cache[video_id] = resolver
            while len(self._resolver_cache) > self.settings.api.resolver_cache_size:
                _, old = self._resolver_cache.popitem(last=False)
                old.close()
            return resolver

    def registry_status(self) -> dict:
        path = self.run_root / "registry" / "run_registry.sqlite3"
        if not path.is_file():
            return {"status": "missing"}
        with RunRegistry(path) as registry:
            run = registry.get_run(self.active_run_id)
            return {
                "run": run,
                "modules": registry.list_status(self.active_run_id),
                "summary": registry.summarize_run(self.active_run_id),
            }


def create_app(
    run_id: str,
    config_path: str | Path = "configs/default.yaml",
    *,
    cors_origins: list[str] | None = None,
) -> FastAPI:
    settings, _ = load_settings(config_path)
    service = PreprocessingService(run_id, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            service.close()

    app = FastAPI(
        title="AIC2026 TV1 + TV3 Evidence API",
        version=__version__,
        lifespan=lifespan,
    )
    origins = cors_origins or settings.api.cors_origins
    if settings.api.cors_allow_credentials and "*" in origins:
        raise ValueError("Wildcard CORS cannot be used with credentials")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=settings.api.cors_allow_credentials,
        allow_methods=settings.api.cors_allow_methods,
        allow_headers=settings.api.cors_allow_headers,
    )

    @app.get("/health")
    def health():
        manifest = service.run_root / "manifest.json"
        payload = read_json(manifest) if manifest.is_file() else {}
        problems = []
        if not service.media:
            problems.append("empty_media")
        if service.temporal is None:
            problems.append("temporal_registry_missing")
        if settings.evidence_catalog.enabled and service.catalog is None:
            problems.append("evidence_catalog_missing")
        status = "ready" if not problems else "degraded"
        return {
            "status": status,
            "active_run_id": service.active_run_id,
            "run_status": payload.get("status"),
            "video_count": len(service.media),
            "problems": problems,
        }

    @app.get("/runs/active")
    def active_run():
        return {"active_run_id": service.active_run_id}

    @app.post("/runs/{new_run_id}/activate", response_model=RunActivationResponse)
    def activate(new_run_id: str):
        try:
            status = service.activate(new_run_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RunActivationResponse(active_run_id=new_run_id, status=status)

    @app.get("/runs/{requested_run_id}/registry")
    def registry(requested_run_id: str):
        if requested_run_id != service.active_run_id:
            raise HTTPException(status_code=409, detail="run is not active")
        return service.registry_status()

    @app.get("/videos")
    def videos():
        return [row.model_dump(mode="json") for row in service.media.values()]

    def _video_path(video_id: str) -> Path:
        media = service.media.get(video_id)
        if media is None:
            raise HTTPException(status_code=404, detail="unknown video_id")
        path = Path(media.original_video_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="original video is missing")
        return path

    @app.api_route("/videos/{video_id}/stream", methods=["GET", "HEAD"])
    def stream_video(video_id: str, request: Request):
        path = _video_path(video_id)
        size = path.stat().st_size
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        range_header = request.headers.get("range")
        if request.method == "HEAD":
            return Response(
                status_code=200,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(size),
                    "Content-Type": media_type,
                },
            )
        if not range_header:
            return FileResponse(path, media_type=media_type, headers={"Accept-Ranges": "bytes"})
        try:
            start, end = _parse_byte_range(range_header, size)
        except (ValueError, TypeError):
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        return StreamingResponse(
            _iter_file_range(path, start, end, settings.api.stream_chunk_size_bytes),
            status_code=206,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Content-Length": str(end - start + 1),
            },
        )

    @app.get("/videos/{video_id}/keyframes")
    def keyframes(video_id: str):
        if video_id not in service.media:
            raise HTTPException(status_code=404, detail="unknown video_id")
        return [row.model_dump(mode="json") for row in service.frames.get(video_id, [])]

    @app.get("/videos/{video_id}/frames/{frame_id}.jpg")
    def original_frame(video_id: str, frame_id: int):
        try:
            decoded = service.resolver(video_id).get_frame_with_record(frame_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown video_id") from exc
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        ok, encoded = cv2.imencode(".jpg", decoded.image_bgr)
        if not ok:
            raise HTTPException(status_code=500, detail="could not encode frame")
        return Response(
            content=encoded.tobytes(),
            media_type="image/jpeg",
            headers={
                "X-Original-Frame-Id": str(decoded.record.frame_id),
                "X-PTS": str(decoded.record.pts),
                "X-Timestamp-Ms": str(decoded.record.timestamp_ms),
            },
        )

    @app.get("/videos/{video_id}/resolve")
    def resolve(video_id: str, timestamp_ms: int, mode: str = "nearest"):
        if mode not in {"nearest", "before", "after"}:
            raise HTTPException(status_code=422, detail="invalid mode")
        try:
            resolved = service.resolver(video_id).resolve_timestamp_record(timestamp_ms, mode=mode)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "requested_timestamp_ms": timestamp_ms,
            "absolute_error_ms": resolved.absolute_error_ms,
            "record": resolved.record.model_dump(mode="json"),
        }

    @app.get("/videos/{video_id}/window")
    def temporal_window(video_id: str, center_ms: int, radius_ms: int = 1500):
        if service.temporal is None:
            raise HTTPException(status_code=409, detail="temporal registry unavailable")
        try:
            window = service.temporal.window_by_radius(video_id, center_ms, radius_ms)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return window.model_dump(mode="json")


    def _query_text(request: SearchRequest) -> str:
        query = (request.query_text or request.question or "").strip()
        if not query:
            raise HTTPException(status_code=422, detail="query_text or question is required")
        return query

    def _require_artifact(relative: str, modality: str) -> Path:
        if not service.media:
            raise HTTPException(status_code=503, detail="dataset is empty")
        path = service.run_root / relative
        if not path.is_file():
            raise HTTPException(status_code=503, detail=f"{modality} artifact unavailable")
        return path

    def _page_payload(page: CatalogPage, envelope: bool) -> list[dict] | dict:
        if not envelope:
            return page.rows
        return {
            "items": page.rows,
            "next_cursor": page.next_cursor,
            "limit": page.limit,
        }

    def _catalog() -> EvidenceCatalog:
        if service.catalog is None:
            raise HTTPException(status_code=503, detail="evidence catalog unavailable")
        return service.catalog

    @app.get("/evidence/catalog/status")
    def evidence_catalog_status():
        _require_artifact("evidence_catalog/manifest.json", "evidence catalog")
        try:
            return validate_evidence_catalog(service.run_root, verify_sources=True)
        except EvidenceCatalogError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/text/search")
    def text_endpoint(request: SearchRequest):
        _require_artifact("text_index/manifest.json", "text index")
        try:
            rows = text_search(
                request.query_id,
                _query_text(request),
                service.active_run_id,
                service.run_root,
                request.limit,
                settings=settings,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Text retrieval unavailable: {exc}") from exc
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/text/index/status")
    def text_index_status():
        _require_artifact("text_index/manifest.json", "text index")
        try:
            return validate_text_index_artifacts(service.run_root, settings, verify_source_checksums=True)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Text index unavailable: {exc}") from exc

    @app.post("/text/index/reload")
    def text_index_reload():
        _require_artifact("text_index/manifest.json", "text index")
        invalidate_text_index_cache(service.run_root)
        try:
            return {"reloaded": True, **validate_text_index_artifacts(service.run_root, settings, verify_source_checksums=True)}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Text index unavailable: {exc}") from exc

    @app.post("/ocr/search")
    def ocr_endpoint(request: SearchRequest):
        _require_artifact("ocr/ocr.jsonl", "OCR")
        try:
            rows = ocr_search(request.query_id, _query_text(request), service.active_run_id, service.run_root, request.limit, settings=settings)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"OCR retrieval unavailable: {exc}") from exc
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/ocr/detections")
    def ocr_detections(
        video_id: str | None = None,
        frame_id: int | None = None,
        limit: int = settings.api.default_page_size,
        cursor: str | None = None,
        envelope: bool = False,
    ):
        _require_artifact("ocr/ocr.jsonl", "OCR")
        try:
            page = _catalog().list_ocr(
                video_id=video_id, frame_id=frame_id, limit=limit, cursor=cursor
            )
        except EvidenceCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _page_payload(page, envelope)

    @app.get("/ocr/{detection_id}/crop")
    def ocr_crop(detection_id: str):
        _require_artifact("ocr/ocr.jsonl", "OCR")
        raw = _catalog().get_ocr(detection_id)
        target = OCRDetection.model_validate(raw) if raw is not None else None
        if target is None or not target.crop_evidence_path:
            raise HTTPException(status_code=404, detail="OCR crop evidence not found")
        crop = (service.run_root / target.crop_evidence_path).resolve()
        try:
            ensure_relative_to(crop, service.run_root)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid OCR evidence path") from exc
        if not crop.is_file():
            raise HTTPException(status_code=404, detail="OCR crop evidence file missing")
        return FileResponse(crop, media_type=mimetypes.guess_type(crop.name)[0] or "image/jpeg")

    @app.post("/asr/search")
    def asr_endpoint(request: SearchRequest):
        _require_artifact("asr/asr.jsonl", "ASR")
        try:
            rows = asr_search(request.query_id, _query_text(request), service.active_run_id, service.run_root, request.limit, settings=settings)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"ASR retrieval unavailable: {exc}") from exc
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/asr/segments")
    def asr_segments(
        video_id: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = settings.api.default_page_size,
        cursor: str | None = None,
        envelope: bool = False,
    ):
        if start_ms is not None and start_ms < 0:
            raise HTTPException(status_code=422, detail="start_ms must be non-negative")
        if end_ms is not None and end_ms < 0:
            raise HTTPException(status_code=422, detail="end_ms must be non-negative")
        if start_ms is not None and end_ms is not None and start_ms > end_ms:
            raise HTTPException(status_code=422, detail="start_ms must be <= end_ms")
        _require_artifact("asr/asr.jsonl", "ASR")
        try:
            page = _catalog().list_asr(
                video_id=video_id,
                start_ms=start_ms,
                end_ms=end_ms,
                limit=limit,
                cursor=cursor,
            )
        except EvidenceCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _page_payload(page, envelope)

    @app.get("/asr/{segment_id}/context")
    def asr_context(segment_id: str, radius_ms: int = 5000):
        if radius_ms < 0 or radius_ms > 600000:
            raise HTTPException(status_code=422, detail="radius_ms must be within [0, 600000]")
        _require_artifact("asr/asr.jsonl", "ASR")
        payload = _catalog().get_asr_context(segment_id, radius_ms)
        if payload is None:
            raise HTTPException(status_code=404, detail="ASR segment not found")
        return payload

    @app.post("/object/search")
    def object_endpoint(request: SearchRequest):
        _require_artifact("objects/objects.jsonl", "object")
        mode = str(request.filters.get("object_mode", settings.object.default_mode))
        if mode not in {"soft_boost", "hard_filter"}:
            raise HTTPException(status_code=422, detail="object_mode must be soft_boost or hard_filter")
        try:
            rows = object_search(request.query_id, _query_text(request), service.active_run_id, service.run_root, request.limit, mode=mode)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Object retrieval unavailable: {exc}") from exc
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/objects/detections")
    def object_detections(
        video_id: str | None = None,
        frame_id: int | None = None,
        label: str | None = None,
        min_confidence: float | None = None,
        include_below_threshold: bool = True,
        limit: int = settings.api.default_page_size,
        cursor: str | None = None,
        envelope: bool = False,
    ):
        _require_artifact("objects/objects.jsonl", "object")
        if min_confidence is not None and not 0.0 <= min_confidence <= 1.0:
            raise HTTPException(status_code=422, detail="min_confidence must be within [0, 1]")
        try:
            page = _catalog().list_objects(
                video_id=video_id,
                frame_id=frame_id,
                label=label,
                min_confidence=min_confidence,
                include_below_threshold=include_below_threshold,
                limit=limit,
                cursor=cursor,
            )
        except EvidenceCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _page_payload(page, envelope)

    @app.post("/metadata/search")
    def metadata_endpoint(request: SearchRequest):
        _require_artifact("metadata/metadata.jsonl", "metadata")
        try:
            rows = metadata_search(request.query_id, _query_text(request), service.active_run_id, service.run_root, request.limit, settings=settings)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Metadata retrieval unavailable: {exc}") from exc
        return [row.model_dump(mode="json") for row in rows]

    @app.get("/metadata/records")
    def metadata_records(
        video_id: str | None = None,
        source: str | None = None,
        limit: int = settings.api.default_page_size,
        cursor: str | None = None,
        envelope: bool = False,
    ):
        _require_artifact("metadata/metadata.jsonl", "metadata")
        try:
            page = _catalog().list_metadata(
                video_id=video_id, source=source, limit=limit, cursor=cursor
            )
        except EvidenceCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return _page_payload(page, envelope)

    return app
