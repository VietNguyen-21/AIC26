# WP13 Integration Boundaries

All JSON is UTF-8 `snake_case`; optional fields are explicit `null` where the owning contract defines them. Every returned or selected submission frame must carry provable canonical original identity or be rejected.

Authority order is official AIC 2026 competition PDF -> AIC2026 Final Pipeline -> AIC 2025 guide for provisional operational submission mechanics only -> current physical/runtime/source evidence -> derived WP13 planning documents. This boundary records implementation state without allowing it to override competition or architecture requirements.

## Common readiness and degradation

Dependencies report the scoped status `READY`, `PARTIAL`, `HANDOVER PENDING`, `CODE GAP`, `INCOMPATIBLE`, or `ACTUALLY MISSING`, plus diagnostics, capability impact, provenance/version and safe fallback. `HANDOVER PENDING` means a known owner delivery has not yet been accepted; `CODE GAP` means required integration/transport/UI is absent despite usable underlying assets or capability; `ACTUALLY MISSING` is reserved for a capability with no verified asset, source, contract or planned handover. HTTP/service health is not `READY` merely because a process starts. Degraded status is visible; unavailable branches never fabricate healthy data.

## WP03 Visual boundary

Consume text-to-frame and supported image/reference-frame-to-frame ranked candidates, FAISS/model/index/mapping/run provenance, canonical identity, ranks/scores, evidence refs, dedup/diversity and aggregation. Four real visual-model FAISS indexes exist in the current smoke run, but their 3/873-video, 892/106,380-frame coverage is `PARTIAL`; the corrected corpus-complete package is `HANDOVER PENDING`. Handover validation checks manifests/digests/index-map/vector counts/video+selected-frame coverage/run compatibility, then freezes and plugs in the accepted root without application redesign. No preprocessing/repair occurs here.

## WP04 boundaries

- **OCR**: canonical frame/time linkage, raw+normalized text, bbox/polygon, confidence, model/run provenance, retrieval rank/index status.
- **ASR**: canonical video, start/end, transcript+normalized text/context, confidence, model/run provenance, retrieval rank/index status.
- **Object**: canonical frame/time, label, bbox/crop ref, confidence, model/run provenance; soft boost/filter semantics by default.
- **Metadata**: evidence values, canonical video/time or frame linkage as applicable, provenance and retrieval/index status.

Each modality is independent and may be unavailable without stopping dense retrieval. WP04 producer/source/contracts and evidence APIs exist, while the corrected OCR/ASR/Object/Metadata artifacts/indexes/evidence are `HANDOVER PENDING`, not `ACTUALLY MISSING` and never silently empty/healthy. After handover, TV5 validates them read-only and freezes the accepted roots; WP13 does not run preprocessing. Any still-absent TV4 rich-evidence adapter is a separate `CODE GAP` and requires its own contract/integration evidence.

## WP08 Feedback boundary

Request carries session/revision, immutable original query, canonical selected reference frame and raw feedback text. Response carries ordered history, immutable original snapshot reference, distinct refined ranked candidates and status/reason. Reset changes active view to original; it does not mutate history or basket. Every refined candidate passes canonical validation. Current WP08 behavior is integrated only where its real contract supports it. Advanced composed-model availability is benchmark-gated and not global P0.

## WP09 Exact-frame boundary (accepted P0 foundation)

Request carries canonical anchor, authoritative media/mapping/run/checksum/decoder provenance, bounded stepping/refinement policy and task/evidence. Response carries actual ordered previous/current/next ORIGINAL frames, direction/boundary, canonical `video_id/frame_id/timestamp_ms`, PTS/time-base audit, selectable proof and explicit degraded reason. Repeated calls support frame-by-frame stepping.

Raw PTS, FPS arithmetic, keyframe/proxy/UI/browser/seek-local ordinals are forbidden as `frame_id`. Stale/conflicting/missing proof fails closed. The coarse canonical anchor may remain selectable; newly decoded neighbors remain nonselectable until proof passes.

E4-1's production resolver, canonical identity, certified-anchor behavior, signed cumulative stepping, ORIGINAL-frame previous/current/next and boundary behavior, proof rejection, live non-sample acceptance, TV4 `/exact-frame/neighbors` integration and automated tests are CLOSED/ACCEPTED. WP09 tracked -> runtime synchronization is complete at 34/34 tracked files with zero missing/hash mismatch and MUST NOT be repeated. WP13 consumes this boundary and adds UI/state/basket regression coverage; the bounded certification sample and `VFR_NOT_LIVE_SAMPLED` are accepted non-blocking residual hardening items, not a reason to redesign the backend.

## TV4 task boundary

- **KIS**: textual request; <=100 continuously ranked canonical candidates with scores/ranks, diversity and full modality/evidence/provenance/degraded status.
- **VQA**: description/question; evidence-grounded candidates, rich EvidencePack, advisory proposal/confidence/verifier/retry/manual state and exact-neighbor support. Empty evidence cannot yield confident automation.
- **TRAKE**: immutable ordered events; <=100 diverse hypotheses where supported, each with one canonical frame per event, event scores/order/provenance and validation status.

TV4 retains WP07 routing/RRF and WP10-WP12 orchestration. It must preserve raw ranks/scores per modality and never directly sum incompatible scores.

## Media/video transport

The physical system already contains 873 original MP4s, corpus-scale keyframes/thumbnails/mappings and canonical frame/time registries. WP04 service source already provides reusable original-video Range streaming, original-frame decode and timestamp/frame resolution semantics. Their existence is upstream capability; it is independent of the pending WP04 modality-data handover.

TV4 browser-safe media/image exposure remains a `CODE GAP`. The narrow TV4 adapter/proxy must reuse or wrap the existing semantics, resolve canonical `video_id` through a configured authoritative registry/root, enforce path containment and allowed media, open read-only, preserve Range/HEAD/206/416 behavior, and return identity-preserving browser-consumable URLs/contracts. Never expose arbitrary filesystem paths or instruct the browser to call random upstream services directly. Never derive canonical identity from playback. Proxy playback, if configured, must retain explicit resolution back to original identity. WP13 player/state integration is a separate UI gap and needs its own acceptance evidence.

## Health/dependency readiness

Probe WP03, WP04 modalities/indexes, WP08, WP09 resolver, VLM/verifier, media registry/root and TV4 orchestration. Return overall and component status, mode, compatible run/config IDs, reason and affected capabilities. Fixture health is labeled fixture-only.

## Submission/export

Input is validated ordered basket state. Existing TV4 retrieval/export utilities, including its current submission helpers, are not approved final contest preparation because they emit incompatible headers/extra fields and TRAKE JSON. WP13 therefore owns contest-safe basket validation, KIS/Q&A/TRAKE serializers, package validator, top-level `submission/` ZIP builder and CLI fallback.

Output is <=100 headerless UTF-8 CSV rows: KIS `<video_id>,<frame_id>`, Q&A `<video_id>,<frame_id>,<approved_answer>`, TRAKE `<video_id>,<frame_id_1>,...,<frame_id_N>`. Standard CSV quoting is serialization, not answer normalization. ZIP is reopened and fail-closed validated. A preparation API fallback is conditional on a separately approved callable seam; manual Codabench upload remains human-controlled. AIC 2026 controls task/scoring semantics and the row limit; AIC 2025 filename/CSV/ZIP/answer-length/attempt mechanics remain explicitly provisional until superseded.

## Evaluation

Pure metric boundary accepts predictions plus authoritative intervals/events and VQA semantic verdicts, returning R-Score/R@k/Final Score and internal metrics with completeness/provenance. Without valid ground truth/verdict it returns `INCOMPLETE`, not guessed scoring. Preprocessing throughput/storage are ingested from validated upstream reports only.
