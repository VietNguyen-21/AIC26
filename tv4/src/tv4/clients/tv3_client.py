"""Client for TV3's FastAPI backend (tv1tv3/TV1_TV3_WP04/src/aic2026/api.py).

Talks the documented `SearchRequest` -> list[`SearchCandidate`] contract over
HTTP (POST /text/search, /ocr/search, /asr/search, /object/search,
/metadata/search). TV4 never reads TV3's on-disk artifacts directly.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Iterable

from ..contracts import SearchCandidate, SearchRequest

_ROUTE_BY_SOURCE = {
    "text": "/text/search",
    "ocr": "/ocr/search",
    "asr": "/asr/search",
    "object": "/object/search",
    "metadata": "/metadata/search",
}


class TV3ClientError(RuntimeError):
    pass


class TV3Client:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> list[dict]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Callers that need a truthful degraded state (notably VQA) must
            # distinguish an unavailable artifact from an empty result set.
            raise TV3ClientError(f"POST {url} failed ({exc.code}): {exc.read()[:300]}") from exc
        except urllib.error.URLError as exc:
            raise TV3ClientError(f"POST {url} failed: {exc}") from exc

    def search(self, route: str, request: SearchRequest) -> list[SearchCandidate]:
        if route not in _ROUTE_BY_SOURCE:
            raise ValueError(f"unknown TV3 route: {route}")
        rows = self._post(_ROUTE_BY_SOURCE[route], request.to_json())
        return [SearchCandidate.from_json(r) for r in rows]

    def _get_payload(self, path: str, params: dict[str, object]) -> object:
        query = urllib.parse.urlencode({key: value for key, value in params.items() if value is not None})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TV3ClientError(f"GET {url} failed ({exc.code}): {exc.read()[:300]}") from exc
        except urllib.error.URLError as exc:
            raise TV3ClientError(f"GET {url} failed: {exc}") from exc
    def _get_records(self, path: str, params: dict[str, object]) -> list[dict]:
        payload = self._get_payload(path, params)
        if isinstance(payload, dict):
            payload = payload.get("items", [])
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise TV3ClientError(f"GET {path} returned malformed evidence records")
        return payload

    # These are deliberately thin public-WP04 catalogue adapters. TV4 retains
    # the returned producer records rather than rebuilding evidence itself.
    def get_ocr_detections(self, *, video_id: str, frame_id: int) -> list[dict]:
        return self._get_records("/ocr/detections", {"video_id": video_id, "frame_id": frame_id, "limit": 100})

    def get_asr_segments(self, *, video_id: str, start_ms: int, end_ms: int) -> list[dict]:
        return self._get_records("/asr/segments", {"video_id": video_id, "start_ms": start_ms, "end_ms": end_ms, "limit": 100})

    def get_asr_context(self, *, segment_id: str) -> list[dict]:
        payload = self._get_payload(f"/asr/{urllib.parse.quote(segment_id, safe='')}/context", {})
        if not isinstance(payload, dict) or not isinstance(payload.get("segments"), list):
            raise TV3ClientError("ASR context returned malformed evidence records")
        return [row for row in payload["segments"] if isinstance(row, dict)]

    def get_object_detections(self, *, video_id: str, frame_id: int) -> list[dict]:
        return self._get_records("/objects/detections", {"video_id": video_id, "frame_id": frame_id, "limit": 100})

    def get_metadata_records(self, *, video_id: str) -> list[dict]:
        return self._get_records("/metadata/records", {"video_id": video_id, "limit": 100})

    def search_all(self, request: SearchRequest, routes: Iterable[str]) -> dict[str, list[SearchCandidate]]:
        out: dict[str, list[SearchCandidate]] = {}
        for route in routes:
            try:
                out[route] = self.search(route, request)
            except TV3ClientError:
                out[route] = []
        return out
