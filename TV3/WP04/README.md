# TV3 / WP04 — Multimodal Retrieval

WP04 consumes immutable TV1 identities and produces versioned OCR, ASR,
object and deterministic metadata artifacts. It follows `AIC2026_Pipeline.md`:
OCR/ASR retrieval stays independent, object output is evidence with an optional
suggested boost, and TV4 owns fusion.

## Setup

```powershell
cd TV3/WP04
python -m pip install -e .
python -m pytest tests -q -p no:cacheprovider
```

The default runtime configuration is `configs/default.yaml`. Its production
model defaults are `deepsolo-parseq-vn`, `chunkformer-ctc-large-vie` with
Silero VAD, and `rf-detr`. Set each `model.factory` to a local callable in the
form `package.module:factory`; optional runtimes are lazy-loaded so a missing
checkpoint becomes a visible modality failure, not a package-import crash.

## Artifacts and provenance

Intermediate artifacts live under:

```text
<run-dir>/wp04/<wp04_artifact_set_id>/<modality>/<video_id>.parquet
```

Every artifact fingerprint incorporates TV1 input checksums, effective
configuration, adapter/VAD versions and normalization version. A video shard
is written atomically before its `ready` status is persisted. `no_audio` is
valid only when TV1 declared audio absent; missing expected audio is `failed`.

## Search handoff

```powershell
python -m wp04.cli search --run-dir data/runs/run-a `
  --preprocess-run-id run-a --artifact-set-id wp04-a `
  --source ocr --query "banh mi"
```

The command emits UTF-8 JSON with canonical `SearchCandidate` records (up to
100). ASR must first be joined to WP05 temporal hypotheses before it can emit
frame candidates; WP04 never invents a frame ID from audio timing.
