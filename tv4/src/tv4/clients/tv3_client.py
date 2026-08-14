"""Client for TV3's FastAPI backend (tv1tv3/TV1_TV3_WP04/src/aic2026/api.py).

Talks the documented `SearchRequest` -> list[`SearchCandidate`] contract over
HTTP (POST /text/search, /ocr/search, /asr/search, /object/search,
/metadata/search). TV4 never reads TV3's on-disk artifacts directly.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
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
            # 503 means that modality's artifact isn't built yet -- treat as
            # "no candidates from this branch" rather than a hard failure.
            if exc.code == 503:
                return []
            raise TV3ClientError(f"POST {url} failed ({exc.code}): {exc.read()[:300]}") from exc
        except urllib.error.URLError as exc:
            raise TV3ClientError(f"POST {url} failed: {exc}") from exc

    def search(self, route: str, request: SearchRequest) -> list[SearchCandidate]:
        if route not in _ROUTE_BY_SOURCE:
            raise ValueError(f"unknown TV3 route: {route}")
        rows = self._post(_ROUTE_BY_SOURCE[route], request.to_json())
        return [SearchCandidate.from_json(r) for r in rows]

    def search_all(self, request: SearchRequest, routes: Iterable[str]) -> dict[str, list[SearchCandidate]]:
        out: dict[str, list[SearchCandidate]] = {}
        for route in routes:
            try:
                out[route] = self.search(route, request)
            except TV3ClientError:
                out[route] = []
        return out
