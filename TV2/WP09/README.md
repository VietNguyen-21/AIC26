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

`status` is `refined`, `partial` (budget exhausted after trustworthy automated
scores) or `manual_only` (frames decode but scorer is unavailable/OOM). A decode
or mapping failure raises/reports `RefinementUnavailable`; it is not converted
to a fake manual result. Every manual-only result retains the coarse frame.

The optional GPU dependency is installed with `pip install -e ".[gpu]"`.
SigLIP2 is lazily loaded only when a real scorer is invoked; CPU tests neither
download models nor claim GPU compatibility. GPU smoke remains a later handoff.

## Benchmark

`wp09.benchmark.compare_refinement_runs` reports Interval Hit@K and p50/p95
latency for labelled exact-frame OFF/ON runs. It calculates evidence only; a
separate release process decides whether the observed delta is sufficient.
