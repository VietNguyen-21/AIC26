"""Batch-manifest loading and validation for externally supplied video collections."""

from __future__ import annotations

import os
import time
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def _column_index(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch.upper()) - 64
    return value - 1


def read_first_sheet(path: str | Path) -> list[list[str]]:
    """Read basic string/numeric cells from an XLSX without openpyxl."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.findall(".//m:t", _NS)))
        workbook = ET.fromstring(z.read("xl/workbook.xml"))
        first = workbook.find("m:sheets/m:sheet", _NS)
        rel_id = first.attrib.get(f"{{{_NS['r']}}}id")
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = None
        for rel in rels:
            if rel.attrib.get("Id") == rel_id:
                target = rel.attrib["Target"]
                break
        if not target:
            raise ValueError("Cannot resolve first worksheet")
        normalized_target = target.lstrip("/")
        if normalized_target.startswith("xl/"):
            sheet_name = normalized_target
        else:
            sheet_name = f"xl/{normalized_target}"
        root = ET.fromstring(z.read(sheet_name))
        rows = []
        for row in root.findall(".//m:sheetData/m:row", _NS):
            values: dict[int, str] = {}
            for cell in row.findall("m:c", _NS):
                ref = cell.attrib.get("r", "A1")
                idx = _column_index(ref)
                cell_type = cell.attrib.get("t")
                v = cell.find("m:v", _NS)
                inline = cell.find("m:is/m:t", _NS)
                raw = inline.text if inline is not None else (v.text if v is not None else "")
                if cell_type == "s" and raw:
                    raw = shared[int(raw)]
                values[idx] = raw or ""
            width = max(values, default=-1) + 1
            rows.append([values.get(i, "") for i in range(width)])
        return rows


def manifest_entries(path: str | Path) -> list[dict[str, str]]:
    rows = read_first_sheet(path)
    if not rows:
        return []
    headers = [x.strip().lower() for x in rows[0]]
    entries = []
    for row in rows[1:]:
        item = {headers[i]: row[i] if i < len(row) else "" for i in range(len(headers))}
        filename = next(
            (item[k] for k in item if "filename" in k or "file name" in k or "tên file" in k), ""
        )
        link = next((item[k] for k in item if "link" in k or "url" in k or "đường dẫn" in k), "")
        if filename or link:
            entries.append({"filename": filename, "url": link, **item})
    return entries


def download_entries(
    entries: list[dict[str, str]],
    output_dir: str | Path,
    include_prefix: str = "Videos_",
    retries: int = 3,
) -> list[Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    downloaded = []
    for entry in entries:
        name = entry.get("filename", "")
        url = entry.get("url", "")
        if not name.startswith(include_prefix) or not url:
            continue
        target = output / name
        if target.exists() and target.stat().st_size > 0:
            downloaded.append(target)
            continue
        part = target.with_suffix(target.suffix + ".part")
        last_error = None
        for attempt in range(retries):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": "AIC2026Downloader/0.1"}
                )
                with (
                    urllib.request.urlopen(request, timeout=120) as response,
                    part.open("wb") as handle,
                ):
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                part.replace(target)
                downloaded.append(target)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                time.sleep(2**attempt)
        if last_error:
            raise RuntimeError(f"Failed to download {name}: {last_error}")
    return downloaded
