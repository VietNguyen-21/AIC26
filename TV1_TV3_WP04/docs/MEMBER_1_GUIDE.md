# Member 1 Guide — TV1

## Mission

TV1 owns deterministic preprocessing and the original-frame identity layer.
Downstream modalities must be able to resolve every selected frame back to the
original video without FPS-based reconstruction.

## Owned modules

```text
src/aic2026/ingest.py
src/aic2026/media.py
src/aic2026/frame_index.py
src/aic2026/autoshot.py
src/aic2026/keyframes.py
src/aic2026/temporal.py
src/aic2026/registry.py
src/aic2026/validation.py
```

The selected keyframe stack uses **AutoShot with the repository's hybrid/fallback
logic**. Model repositories/checkpoints are external and must not be committed.

## Required invariants

1. Raw video is the source of truth.
2. `frame_id` is zero-based original decode identity.
3. PTS + `time_base` are preferred for exact timeline mapping.
4. VFR material must not be mapped by `round(timestamp * fps)`.
5. Keyframes preserve the original identity fields consumed by TV3.
6. Run artifacts are deterministic/resumable and validated before handoff.

## Handoff to TV3

At minimum, TV3 relies on stable values for:

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
keyframe path/checksum when applicable
```

TV1 should not rename or reinterpret these fields without updating the shared
contract and tests.

## Development

```powershell
python -m pip install -e ".[dev]"
python -m compileall -q src tests
pytest -q
```

Use `configs/external_video_smoke.yaml` for dependency-light structural testing.

Do not commit raw videos, extracted media, frame-index outputs, run directories,
model weights, or personal paths.
