# Specification Quality Checklist: Complete Contest-Ready WP13

`[x]` means the revised planning set explicitly covers the item; it does not claim implementation/live acceptance.

## Authority, scope and dependency classification

- [x] Official AIC 2026 semantics are authoritative; AIC 2025 packaging/answer-length/attempt mechanics are provisional.
- [x] Final target product, current available artifacts and final live acceptance are separate concepts.
- [x] Claim 1 is EXTERNAL ARTIFACT DEPENDENCY; WP13 never runs WP03 preprocessing.
- [x] Claim 2 is EXTERNAL CODE + ARTIFACT DEPENDENCY; WP13 neither repairs the producer nor runs WP04 preprocessing unless reassigned.
- [x] Claim 3 is OUR IMPLEMENTATION RESPONSIBILITY and P0.
- [x] Implementation proceeds while Claim 1/2 handovers remain pending; only relevant final-live tasks depend on them.
- [x] No task performs upstream preprocessing, index rebuild, corpus backfill or persistent full-corpus replacement mapping.

## Capability completeness

- [x] KIS: textual top-100, continuous rank, diversity, evidence/provenance, exact correction, feedback, basket, logs and dense/degraded fallback.
- [x] Feedback: original query, canonical reference, raw text, history, distinct original/refined results, reset, no basket mutation and candidate revalidation.
- [x] Advanced feedback model remains benchmark-gated/optional, not a global P0 blocker.
- [x] VQA: evidence retrieval, proposal/confidence/verifier, OCR/ASR/Object/multiframe, retry, manual fallback, edit/confirm and exact approved-answer preservation.
- [x] TRAKE: semantic events/count/order, hypotheses, temporal consistency, timeline, lock/unlock, correction, exact frames and fail-closed validation.
- [x] Visual, OCR, ASR, Object and Metadata retrieval/evidence are represented; Object is soft by default.
- [x] Routing, low-confidence multi-route and mandatory RRF retain independent raw ranks/scores/provenance.
- [x] EvidencePack/UI includes frames, OCR bbox, ASR context, Object evidence, source/run/model/config provenance.
- [x] UI includes all three modes, top-100, player, neighbors/stepping, feedback, VQA controls, TRAKE controls, basket and keyboard shortcuts.

## Exact-frame and media P0

- [x] Current, actual immediate previous and actual immediate next ORIGINAL frames plus repeated stepping are P0.
- [x] Newly inspected neighbors are selectable only after canonical proof; display-only is not final acceptance.
- [x] Proof covers anchors/global ID, boundaries, VFR, PTS/time-base, seek/back-seek, duplicate/missing/nonmonotonic PTS, cross-anchor and stale provenance.
- [x] Raw PTS, nominal FPS, keyframe/proxy/UI/browser/seek-local ordinals are forbidden as `frame_id`.
- [x] Original-video transport is read-only, registry/root configured, path-contained and range/seek capable without playback-derived identity.

## Submission, evaluation and operations

- [x] Canonical basket, <=100, headerless KIS/Q&A/TRAKE CSV, answer-preserving CSV quoting, validation, `submission/` ZIP and fail-close are explicit.
- [x] UI and CLI preparation paths are mandatory; API fallback is conditional on an approved seam; upload is human-controlled.
- [x] Official metrics and internal Hit@K/VQA/TRAKE/latency/time-first-correct/error metrics are explicit.
- [x] Preprocessing throughput/storage is ingested from validated reports without preprocessing.
- [x] Benchmark/Ablation/Error Analysis/Mock/Iterate and metric-ready vs official-dataset-ready are separate.
- [x] Deterministic fixture, current partial live and final live modes are distinct; degraded status is visible.
- [x] Compose, config lock, dependency probes, read-only mounts, WP13 state persistence, backup/restore, runbook and target/non-owner handoff are explicit.
- [x] Final release requires accepted handovers, exact proof, live integration/E2E and three consecutive P0-clean mocks.

## Quality

- [x] Valid existing FR-001-FR-057 IDs are preserved; new requirements continue FR-058-FR-080.
- [x] Requirements are testable and map to concrete tasks/tests.
- [x] External gaps are documented without shrinking target scope or falsely claiming live readiness.
- [x] No unresolved human decision blocks E4 implementation.
