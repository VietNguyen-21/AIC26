# WP09 — exact-frame refinement

WP09 refines one upstream coarse candidate against an **original video**. It is
not corpus retrieval, a UI, or submission storage. TV4 supplies text, task and
TRAKE policy; TV5 displays original-video frame references and owns final
selection.

The `RefineRequest` must include canonical `video_path`, `RefinementContext`
(`preprocess_run_id`, media/mapping references and versions) and a bounded
`DecodeBudget`. A decoder factory must return a `MappedVideoDecoder` (or an
equivalent adapter) that resolves every PyAV PTS through TV1's
`FrameMappingResolver`. Frame IDs are never created from FPS, decoder indexes,
keyframe sequences or proxy files.

## JSON CLI

```powershell
python -m wp09 refine --request request.json --config configs/default.yaml --decoder-factory team_adapter:decoder_for_request --scorer-factory team_adapter:scorer_for_request
```

The command prints one JSON `RefineResult` to stdout; errors are JSON on stderr.
There is intentionally no default path-from-video-ID logic: the external decoder
factory is responsible for canonical media and mapping resolution.

Custom decoders must expose `mapping_guaranteed = True` and honor the
`max_frames` argument on `frames_between`; `MappedVideoDecoder` provides both.
WP09 rejects undecorated duck-typed decoders before it reads video data.

## Exact-neighbor identity contract (E4-1A)

Selected WP02 records are anchors, not a complete original-frame authority.
`run_v1_batch1`'s producer code assigns a selected record with
`frame.index if hasattr(frame, "index") else frame_idx_in_stream`; the run
records do not preserve which branch/version was used. Consequently, an anchor
PTS and a locally decoded offset cannot prove a neighbor's canonical global
`frame_id`.

`ExactFrameResolver` now makes a neighbor selectable only when an integration
supplies a read-only `CanonicalFrameAuthority` record for that exact original
PTS. It also verifies the original path, SHA-256, time base,
`preprocess_run_id`, mapping/media references, and an explicit certified
producer/resolver ordering compatibility statement. It writes no map and does
not backfill artifacts. Without that authority, every neighbor response is
`canonical_identity_unproven` and non-selectable; agreement with another
selected anchor is only diagnostic, never proof.

For repeated UI stepping, retain `certified_anchor_frame_id` and a cumulative
requested offset. Do not promote a returned neighbor into a trusted anchor
unless a future proof policy explicitly says so.

`status` is `refined`, `partial` (budget exhausted after trustworthy automated
scores) or `manual_only` (frames decode but scorer is unavailable/OOM). A decode
or mapping failure raises/reports `RefinementUnavailable`; it is not converted
to a fake manual result. Every manual-only result retains the coarse frame.

The optional GPU dependency is installed with `pip install -e ".[gpu]"`.
SigLIP2 is lazily loaded only when a real scorer is invoked; CPU tests neither
download models nor claim GPU compatibility. GPU smoke remains a later handoff.

## Runtime bounds

The in-process decoded-frame cache is LRU-bounded to 32 canonical windows and
32 request aliases by default. Idle entries expire after 300 seconds; eviction
also removes request aliases, so they cannot retain decoded RGB pixel data.
Deployments can set `cache_max_entries` and `cache_ttl_seconds` under `wp09`.

SigLIP2 starts with batches of eight frames. A CUDA OOM clears available CUDA
cache and retries the same unscored frames with progressively smaller batches;
an OOM at one frame preserves the existing `manual_only` fallback.

## Benchmark

`wp09.benchmark.compare_refinement_runs` reports Interval Hit@K and p50/p95
latency for labelled exact-frame OFF/ON runs. It calculates evidence only; a
separate release process decides whether the observed delta is sufficient.
