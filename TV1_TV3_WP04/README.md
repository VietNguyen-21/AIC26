# AIC2026 — TV1 + TV3 Source

Minimal shared source repository for the **Member 1 (TV1)** and **Member 3 (TV3)**
workstreams of AI Challenge 2026.

This repository intentionally contains **source code, selected-model adapters,
configuration templates, tests, and only three ownership/contract documents**.
Raw competition data, Ground Truth workspaces, model checkpoints, downloaded
third-party repositories, generated reports, caches, and machine-specific paths
must stay outside Git.

## 1. Ownership

### TV1 — preprocessing and frame identity
TV1 owns the source-of-truth media/frame layer:

- raw-video ingest and media inspection;
- deterministic audio extraction;
- original-frame index based on decode order / PTS / time base;
- AutoShot/hybrid keyframe selection;
- keyframe-to-original-frame mapping;
- temporal registry and run validation.

Important modules:

```text
src/aic2026/
  ingest.py
  media.py
  frame_index.py
  autoshot.py
  keyframes.py
  temporal.py
  registry.py
  validation.py
```

### TV3 — OCR / ASR / Object / text evidence
TV3 consumes TV1 identities and never reconstructs frame IDs from FPS.

Selected production stack:

```text
OCR     : DeepSolo + PARSeq
VAD     : Silero VAD
ASR     : ChunkFormer-CTC-Large-Vie
Object  : RF-DETR
```

Important modules:

```text
src/aic2026/
  ocr.py
  asr.py
  objects.py
  metadata.py
  modalities.py
  evidence_catalog.py
  text_index.py
```

External-model adapters:

```text
models/adapters/
  autoshot.py
  deep_solo_parseq.py
  chunkformer.py
  rfdetr.py
```

## 2. Repository layout

```text
backend/                  FastAPI evidence/search entrypoint
benchmarks/               Small contract fixtures for retrieval evaluation
configs/                  Minimal committed configuration
docs/                     TV1 guide, TV3 guide, shared contract
models/adapters/          Four selected model adapters
scripts/                  Small source-audit/archive utilities
src/aic2026/              Production Python package
tests/                    Unit/integration/contract/regression tests
```

Committed configs are intentionally limited to:

```text
configs/default.yaml
configs/competition.example.yaml
configs/external_video_smoke.yaml
```

`configs/default.yaml` is dependency-light and keeps heavy modalities disabled.
`configs/competition.example.yaml` documents the selected competition stack.
Copy it to a local ignored file before putting machine-specific checkpoint paths:

```powershell
New-Item -ItemType Directory -Force .\configs\local | Out-Null
Copy-Item .\configs\competition.example.yaml .\configs\local\competition.yaml
```

Do **not** commit `configs/local/competition.yaml`.

## 3. Install

Python 3.11 is the common development target.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Heavy model runtimes/checkpoints remain external. Install only the optional
runtime extras needed on the machine that runs that modality.

## 4. Core checks

```powershell
python -m compileall -q src backend tests scripts models
pytest -q
```

Optional quality checks:

```powershell
ruff check src tests backend scripts models
mypy src/aic2026/evidence_catalog.py src/aic2026/model_certification.py src/aic2026/benchmarking.py
```

Generated schemas are not committed. Export them when another component needs
a fresh contract bundle:

```powershell
aic export-schemas --output .\configs\schemas
```

`configs/schemas/` is ignored because `src/aic2026/contracts.py` and
`src/aic2026/config.py` are the source of truth.

## 5. Typical commands

Structural/dependency-light smoke:

```powershell
aic preprocess --input <VIDEO_OR_FOLDER> --run-id smoke --config configs/external_video_smoke.yaml
```

Competition machine:

```powershell
aic preprocess --input <VIDEO_OR_FOLDER> --run-id competition --config configs/local/competition.yaml
```

Check that a working tree is safe to share:

```powershell
python scripts/check_release_package.py --root . --strict
```

## 6. Identity contract

TV3 must copy TV1 identity fields. In particular:

```text
preprocess_run_id
video_id
frame_id
decode_index
pts
time_base
raw_timestamp_ms
timeline_origin_ms
timestamp_ms
```

`frame_id` is the zero-based original decode identity. Never derive it as
`round(timestamp * fps)`.

See `docs/TV1_TV3_CONTRACT_COMPATIBILITY.md`.

## 7. TV4 consumer contract

TV4 should consume canonical `SearchCandidate` records instead of reading
modality artifacts directly. TV3 exposes the following search surfaces:

```text
POST /text/search
POST /ocr/search
POST /asr/search
POST /object/search
POST /metadata/search
```

Candidate localization/submission policy:

```text
OCR
  exact TV1 source frame
  localization_required = false
  submittable = true

Object
  exact TV1 source frame; soft constraint by default
  localization_required = false
  submittable = true

ASR resolved by TemporalRegistry
  exact representative frame
  localization_required = false
  submittable = true

ASR unresolved
  localization_required = true
  submittable = false

Metadata
  video-level soft evidence only
  localization_required = true
  submittable = false
```

TV4 owns query decomposition, multi-event orchestration, candidate fusion/RRF,
score/rank normalization, temporal reranking, event chaining, feedback/reasoning,
and final ranking.

Development compatibility can be checked with `aic verify-tv3-handoff`. The final
production handoff should use:

```powershell
aic verify-tv3-handoff --run-id <RUN_ID> --config configs/local/competition.yaml --require-stable
```

The production gate requires all required TV3 artifacts, a valid Evidence
Catalog, a valid persistent Text Index, a matching handoff contract, and a sealed
stable run/handoff manifest.

## 8. Data / model / privacy policy

Never push these to the shared repository:

- `TEST_DATA/`, raw L21–L30 videos, DEV/TEST media;
- OCR/ASR/Object Ground Truth, crops, contact sheets, review states;
- `.venv`, caches, local databases, generated reports;
- model weights (`*.pt`, `*.pth`, `*.ckpt`, `*.bin`, etc.);
- downloaded DeepSolo/PARSeq/ChunkFormer/RF-DETR repositories;
- `configs/local/`;
- `.env` or credentials;
- machine-specific absolute paths or usernames.

The Ground Truth workspace belongs outside this repository, for example under
the team's local/external `TEST_DATA/AIC2026_GT_ANNOTATION` storage.

## 9. Documents kept intentionally

Only these human-facing documents are maintained:

- `docs/MEMBER_1_GUIDE.md`
- `docs/MEMBER_3_GUIDE.md`
- `docs/TV1_TV3_CONTRACT_COMPATIBILITY.md`

Everything else should be expressed by code, tests, Git history, or issue/PR
discussion instead of duplicated status documents.
