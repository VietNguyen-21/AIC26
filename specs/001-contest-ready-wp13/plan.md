# Implementation Plan: Complete Contest-Ready WP13

**Branch**: `team/tv5-ui-evaluation-release` | **Feature**: `001-contest-ready-wp13` | **Date**: 2026-08-17
**Scope of this revision**: planning only. No production code, preprocessing, runtime mutation, branch change, commit or push.

## Outcome and gates

Build the complete Final-Pipeline WP13 product: operator UI for KIS, reference-frame Feedback, VQA and TRAKE; canonical original-video/exact-frame inspection; evidence/provenance; safe basket and submission; official/internal evaluation; telemetry; fixture/degraded operation; and deployable/recoverable release.

Two gates are intentionally separate:

- **Implementation Gate**: contracts and test-first work are executable now with fixtures and every authoritative artifact currently available. Status is scoped as `READY`, `PARTIAL`, `HANDOVER PENDING`, `CODE GAP`, `INCOMPATIBLE` or `ACTUALLY MISSING`; a pending owner handover or missing TV4 adapter does not fail unrelated work.
- **Final Live Acceptance Gate**: corrected WP03/WP04 handovers accepted read-only; the CLOSED/ACCEPTED E4-1 exact-frame foundation remains regression-protected while consumed by WP13; configuration/artifacts frozen; live coverage/integration/E2E, submission, evaluation, three P0-clean mocks, target-machine recovery and non-owner handoff pass.

Required progression:

`IMPLEMENT NOW -> TEST CURRENT ARTIFACTS -> CONTINUE PARALLEL DEVELOPMENT -> RECEIVE HANDOVER -> READ-ONLY VALIDATE -> FREEZE -> COVERAGE -> LIVE INTEGRATION -> E2E -> MOCK -> TARGET MACHINE -> FINAL LIVE RELEASE`

## Dependency ownership

| Class | Work | Rule |
|---|---|---|
| EXTERNAL ARTIFACT DEPENDENCY | Claim 1: corrected corpus-complete WP03/FAISS handover | Current 3/873-video, 892/106,380-frame smoke run supports only partial integration. WP13 never runs WP03 preprocessing. |
| EXTERNAL ARTIFACT HANDOVER DEPENDENCY | Claim 2: corrected OCR/ASR/Object/Metadata artifacts/indexes/evidence | WP04 producer source/contracts and media/evidence service semantics exist. WP13 implements consumers/degradation now; it neither repairs nor runs the producer unless explicitly reassigned. |
| CLOSED / ACCEPTED FOUNDATION | E4-1 WP09 exact-frame plus tracked/runtime synchronization | Consume and regression-protect; do not redesign, rebuild or resynchronize WP09. |
| OUR IMPLEMENTATION RESPONSIBILITY | TV4 media/evidence/Feedback adapters plus WP13 UI/basket/submission/evaluation/deployment | Begin immediately. Corrected Claim 1/2 artifacts are prerequisites only for their final-live acceptance slices. |

## Authority and technical constraints

- Authority order is official AIC 2026 competition PDF -> AIC2026 Final Pipeline -> AIC 2025 guide for provisional operational submission mechanics only -> current physical/runtime/source evidence -> derived WP13 planning documents. Current limitations never reduce higher-authority requirements.
- Official AIC 2026 semantics govern KIS, VQA, TRAKE and metrics. AIC 2025 filename/CSV/ZIP/answer-length/attempt mechanics remain provisional.
- Original MP4 and WP00-WP02 identity are authoritative. Never use raw PTS, nominal FPS arithmetic, `keyframe_seq`, proxy/UI/browser/seek-local ordinals as `frame_id`.
- RRF is the mandatory fusion baseline; raw scores from unrelated spaces are not combined directly. Object remains soft by default.
- No upstream preprocessing, corpus backfill, temporal/index rebuild or new persistent full-corpus frame mapping. Bounded on-demand original decoding and provenance-safe cache are allowed.
- Future functional changes are tracked-first in their owning source. WP09 tracked -> runtime synchronization is already complete (34/34 tracked files identical, zero missing/hash mismatch) and MUST NOT be repeated by this plan.

## Current source findings to retain

| Seam | Current evidence | Planned correction |
|---|---|---|
| WP09 / TV4 exact frame | E4-1 production resolver, canonical proof, certified anchors, signed cumulative stepping, ORIGINAL-frame neighbors/boundaries and `/exact-frame/neighbors` are accepted; WP09 runtime sync is complete | Consume from WP13; retain fail-closed selection and regression coverage; optional hardening remains non-blocking |
| Media | 873 original MP4s and corpus mappings exist; WP04 source already provides Range streaming, original-frame decode and timestamp/frame resolution; TV4 has no browser-facing safe route | Characterize existing semantics, then wrap/adapt minimally through TV4 with registry containment, read-only Range behavior and identity tests |
| Health | reports config construction, not real dependency readiness | Probe TV1/WP03/WP04/WP08/WP09/VLM/media and expose classified degradation |
| VQA | evidence request omits question/query; flattened evidence; unsafe manual predicate; rule fallback can verify any nonempty text | Rich evidence contract/wiring, verifier boundary, retry/abstain/manual semantics |
| Feedback | WP08 preserves original query, history and reference identity; no TV4/WP13 seam | Integrate supported service contract; keep advanced four-model ranker benchmark-gated |
| Submission | TV4 emits headers/extra fields and TRAKE JSON | Independent WP13 headerless CSV/export/package validator |
| Fixtures | minimal and omit Feedback, rich evidence, neighbors/degradation | Deterministic contract-valid fixture families |

## Architecture workstreams

### A. Governance and read-only readiness

Create a WP13-facing validator that only reads artifacts and reports `READY`, `PARTIAL`, `HANDOVER PENDING`, `CODE GAP`, `INCOMPATIBLE`, or `ACTUALLY MISSING`. WP03 checks manifests, digests, index-map consistency, vector/video/frame coverage, canonical mapping and run compatibility. WP04 checks each handed-over modality's records, schema, linkage/timing/evidence/provenance and retrieval index while reporting the known corrected delivery as `HANDOVER PENDING`. Expected coverage should come from authoritative registries; current 873/106,380 counts are audit expectations, not scattered production constants.

### B. Consume accepted exact-frame and close the media transport CODE GAP

E4-1 exact-frame backend work is CLOSED/ACCEPTED. Preserve its canonical proof and fail-closed selectability while connecting the WP13 inspector, repeated stepping and basket guards; do not reopen the resolver or treat the bounded certification sample/`VFR_NOT_LIVE_SAMPLED` as a current P0 blocker. For media, first characterize the existing WP04 Range/original-frame/resolve semantics with regression goldens, then expose the smallest browser-safe TV4 adapter with authoritative registry lookup, path containment, read-only Range behavior and identity-preserving responses. Browser playback never supplies identity.

### C. TV4 boundary repair

Retain TV4 as WP13's application boundary. Add/repair canonical identity, exact-neighbor, safe media, rich evidence, Feedback, VQA proposal/verifier, dependency health and degraded semantics. Preserve KIS/VQA/TRAKE orchestration, routing, RRF, modality provenance and fallback behavior. Do not invent unsupported WP08 behavior.

### D. WP13 shell and state

Implement configurable fixture/current-partial-live/final-live modes; explicit dependency status; durable atomic operator drafts; typed adapters; immutable snapshots; keyboard command registry; telemetry. Persist only WP13-owned mutable state and revalidate on restore.

### E. Operator workflows

- **KIS**: textual query, top 100, continuous rank, diversity, provenance, exact correction, selection, logs and dense/degraded fallback.
- **Feedback**: original query + canonical reference + feedback, history/revisions, distinct original/refined snapshots, reset, no basket mutation, candidate revalidation. Advanced model optional behind benchmark approval.
- **VQA**: evidence-grounded candidates, local window/exact correction, OCR/ASR/Object/multi-frame evidence, advisory proposal/confidence/verifier, controlled retry, manual fallback, edit/confirm, byte-faithful approved answer.
- **TRAKE**: immutable ordered semantic events, coverage/video hypotheses, timeline, locks, corrections, exact event frames, count/order validation and diverse hypotheses where upstream supplies them. Never sort to redefine semantic order.
- **Evidence/UI**: OCR bboxes/polygons, ASR timing/context, object bboxes/crops/labels, selected original frames, source/rank/score/run/model/config provenance, keyboard shortcuts.

### F. Basket, submission and fallbacks

Canonical guard precedes basket entry. Export headerless UTF-8 task-shaped CSV with standards-compliant quoting and <=100 rows. Preserve approved VQA text exactly and TRAKE count/order. Build and reopen-validate ZIP with top-level `submission/`. Provide UI and CLI paths; add an API fallback only if an approved callable submission/preparation seam exists. Actual Codabench upload remains human-controlled.

### G. Evaluation and operations

Implement organizer-golden R-Score/R@k/Final Score plus Video/Frame Hit@K, valid VQA metrics, TRAKE alignment, latency p50/p95, time-to-first-correct and submission error rate. Ingest validated preprocessing throughput/storage reports; never rerun preprocessing for metrics. Support benchmark/ablation/error-analysis/mock reports, telemetry, Docker Compose, config lock, backup/restore, runbook and target-machine acceptance.

## Progressive verification

### Phase A - current available artifacts

Run unit/contract/fixture suites for all workflows; accepted exact-frame regression and WP13-consumer tests; current WP03 3-video integration; current WP08 contract; WP04 handover-pending/degraded behavior; WP04 media semantic goldens plus TV4 adapter tests; basket; CSV/ZIP; metrics; telemetry; Compose/recovery; keyboard/manual UI verification. External handover state produces a classified status and does not fail unrelated tests.

### Phase B - corrected handover

For WP03 and WP04: validate read-only, schema/digests/coverage/provenance/linkage/index, smoke services, freeze roots/config, then rerun Visual/OCR/ASR/Object/Metadata, RRF, KIS/Feedback/VQA/TRAKE, exact-frame, submission, evaluation, full E2E, three mocks and target-machine acceptance. Increased coverage must require no application redesign.

## Critical path

`planning reconciliation/review -> media characterization/regression goldens -> safe TV4 media/image transport -> fixture-first WP13 shell + KIS vertical slice -> Feedback -> safe VQA -> TRAKE -> submission pipeline -> evaluation/operations -> corrected WP03/WP04 handover validation -> full live E2E/mocks/release`

## Parallel work while handovers are pending

After contract reconciliation, these proceed independently: readiness validator, accepted exact-frame consumer regressions, media boundary characterization/transport, WP13 shell, current-artifact KIS, Feedback UI/state/current WP08 integration, VQA confirm/edit, TRAKE state machine, evidence placeholders, basket/keyboard shortcuts, exporter/ZIP/CLI, metrics/report ingestion/telemetry, fixtures/degraded tests, Compose, backup and runbook.

## Release acceptance

- No known P0; no raw-PTS identity; accepted exact-neighbor proof remains enforced end-to-end through UI and basket integration.
- Claim 1 and Claim 2 accepted and frozen; all live dependencies honestly healthy/degraded.
- Official metric goldens and submission/package goldens pass; official-dataset readiness claimed only with valid ground truth.
- Three consecutive mock competitions without known P0 failure.
- Fresh target-machine deployment, backup/recovery and non-owner operation pass with cross-review.

## Human decisions

None required for this reconciliation. Implementation begins only after independent document review. Later work stops if correctness evidence shows a forbidden persistent full-corpus mapping/rebuild is necessary, an official 2026 submission guide changes semantics, or a new cross-module contract/mandatory dependency requires approval.
