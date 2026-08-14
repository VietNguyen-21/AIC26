# Member 3 Guide — TV3

## Mission

TV3 builds searchable text/object evidence on top of TV1 frame/media identity.

Selected stack:

```text
OCR     = DeepSolo + PARSeq
VAD     = Silero VAD
ASR     = ChunkFormer-CTC-Large-Vie
Object  = RF-DETR
```

No alternate OCR/ASR/VAD/Object production fallback stack is enabled in this selected branch.

## Owned modules

```text
src/aic2026/ocr.py
src/aic2026/asr.py
src/aic2026/objects.py
src/aic2026/metadata.py
src/aic2026/modalities.py
src/aic2026/evidence_catalog.py
src/aic2026/text_index.py
```

Selected external adapters:

```text
models/adapters/deep_solo_parseq.py
models/adapters/chunkformer.py
models/adapters/rfdetr.py
```

Shared integration modules such as `contracts.py`, `config.py`,
`fingerprints.py`, `preprocessing.py`, `validation.py`, `api.py`,
`batch_manifest.py`, and `model_certification.py` must remain compatible with
TV1 identity.

## Configuration

Committed configs:

```text
configs/default.yaml
configs/competition.example.yaml
configs/external_video_smoke.yaml
```

For a real model machine:

```powershell
New-Item -ItemType Directory -Force .\configs\local | Out-Null
Copy-Item .\configs\competition.example.yaml .\configs\local\competition.yaml
```

Fill checkpoint/launcher paths only in `configs/local/competition.yaml`.
That directory is ignored by Git.

## Identity rule

Never create frame identity from FPS. OCR/Object records copy TV1 frame identity,
and ASR records stay on the source-audio timeline.

Never rewrite:

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

## Model evidence is not Ground Truth

DeepSolo+PARSeq, ChunkFormer, and RF-DETR outputs are proposals/evidence.
Ground Truth is created in the separate GT workspace after human review,
coverage checking, validation, and freeze. GT artifacts are not committed here.

## Development checks

```powershell
python -m pip install -e ".[dev]"
python -m compileall -q src backend tests models
pytest -q
```

Generate fresh schemas only when required:

```powershell
aic export-schemas --output .\configs\schemas
```

Before sharing:

```powershell
python scripts/check_release_package.py --root . --strict
```

## TV4 handoff gate

TV4 consumes canonical `SearchCandidate` records. For development, use
`aic verify-tv3-handoff`. For a final production handoff, first validate and
seal the run with `aic mark-stable`, then require the stable gate:

```powershell
aic verify-tv3-handoff --run-id <RUN_ID> --config configs/local/competition.yaml --require-stable
```

The stable gate requires a valid Evidence Catalog, valid persistent Text Index,
matching handoff contract/policies, registry status `stable`, and a stable
handoff manifest with an artifact-state fingerprint.
