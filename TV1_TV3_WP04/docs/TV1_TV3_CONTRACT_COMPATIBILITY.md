# TV1 ↔ TV3 Contract Compatibility

This document is the maintained compatibility contract between the TV1
preprocessing/frame layer and the TV3 evidence layer.

## 1. Source of truth

TV1 owns original-video/frame identity. TV3 consumes it.

`frame_id` means the **zero-based original decode identity**. It is not an FPS
estimate and must never be reconstructed with `round(timestamp * fps)`.

For exact mapping, preserve the original decode/timeline fields whenever present:

```text
preprocess_run_id
video_id
frame_id
decode_index
pts
dts (when available)
time_base
raw_timestamp_ms
timeline_origin_ms
timestamp_ms
```

## 2. TV1 → TV3 inputs

TV3 may consume:

- media/audio artifacts and their checksums;
- original-frame index records;
- selected keyframes that resolve to exactly one original frame;
- temporal registry records;
- run/config/model provenance.

A downstream modality may add evidence fields, but must not mutate TV1 identity.

## 3. TV3 selected model stack

```text
OCR     DeepSolo detector + PARSeq recognizer
VAD     Silero VAD
ASR     ChunkFormer-CTC-Large-Vie
Object  RF-DETR
```

Model repositories and checkpoints stay outside Git. The committed
`configs/competition.example.yaml` contains placeholders only.

## 4. OCR contract

OCR evidence preserves the source keyframe identity and adds text evidence such
as normalized text, normalized bbox/polygon, confidence, crop checksum/path, and
model/checkpoint provenance.

## 5. ASR contract

VAD/ASR evidence uses the source-audio timeline. Segments preserve deterministic
start/end times and model provenance. Temporal linking to frames is a downstream
mapping step; ASR must not invent frame IDs.

## 6. Object contract

Object evidence preserves the source frame identity and adds canonical/raw label,
normalized `xyxy` bbox, confidence, count/spatial evidence, and model provenance.

Canonical bbox invariant:

```text
0 <= x1 < x2 <= 1
0 <= y1 < y2 <= 1
```

## 7. TV4 candidate localization policy

Canonical TV3 `SearchCandidate` provenance uses these rules:

```text
OCR       exact source frame        submittable=true
Object    exact source frame        submittable=true
ASR       temporal window           false until TemporalRegistry resolves it
Metadata  video-level soft evidence submittable=false
```

Exact-frame candidates use `frame_resolution=source_keyframe`. Resolved ASR uses
`frame_resolution=temporal_registry`. TV4 should respect the explicit
`submittable`/`localization_required` fields instead of inferring policy from
modality names.

## 8. Ground Truth separation

Model evidence is not Ground Truth. OCR/ASR/Object GT creation, human review,
DEV/TEST split artifacts, crops, dashboards, and freeze files live outside this
source repository.

## 9. Change rule

Any change to identity semantics, required fields, timestamp interpretation, or
bbox conventions requires:

1. code change;
2. contract/schema/test change;
3. TV1 + TV3 review before merge.

Generated schemas are derived from `src/aic2026/contracts.py` and
`src/aic2026/config.py`; they are not committed in this minimal repository.
