# WP13 State Model

Upstream records remain owned upstream. WP13 stores presentation, operator decisions, validation, evaluation and operational state; it references rather than duplicates artifact schemas.

| Entity | Required WP13-owned state | Integrity rule |
|---|---|---|
| `QuerySession` | session/query ID, mode `KIS|VQA|TRAKE`, original query, question, immutable ordered events, filters, runtime/config/fixture version, lifecycle | Original query/events never inferred from UI labels or refined results. |
| `CanonicalFrameIdentity` | `video_id`, original integer `frame_id`, PTS/time-base-derived `timestamp_ms`, anchor/mapping/run/media/checksum/decoder provenance, validation status | Immutable; raw PTS/keyframe/proxy/UI/browser/seek-local ordinal is never identity. |
| `PresentedCandidate` | query/event, rank, canonical identity, source, raw rank/score, fused score, confidence, evidence refs, model/run provenance, degraded flags | Rank is continuous within a returned list; missing identity makes candidate nonselectable. |
| `EvidencePresentation` | selected original frames, OCR raw/normalized text+bbox/polygon+confidence, ASR text/timing/context+confidence, Object label+bbox/crop+confidence, Metadata, source/model/run refs | Missing modalities explicit; empty evidence cannot support confident VQA. |
| `FeedbackSession` | immutable original-query/result snapshot, canonical reference, ordered raw feedback events, revisions/history, refined snapshots, active view, status | Refinement never mutates original snapshot or basket; refined candidates revalidate independently. |
| `ExactFrameInspection` | anchor, inspected ordered original frames, direction/step count/boundaries, selectable flag, proof/provenance, degraded reason | Only validated canonical frames are selectable; unresolved is fail-closed. |
| `VQAProposal` | candidate/evidence, proposed answer, pre-approval normalization, confidence, verifier outcome, retry count, model/status | Advisory only; empty evidence cannot be confidently proposed. |
| `VQAApproval` | exact operator-edited text, confirmed flag/action/time, candidate/evidence revision | Approved bytes are immutable through export except CSV escaping. |
| `TRAKEState` | immutable `(event_index,text)` positions, candidate hypotheses, one frame/slot, locks, correction audit, count/order/video validation | Semantic position is authoritative; sorting frame IDs cannot reorder events. |
| `SubmissionBasket` | query-scoped ordered entries, visible/export rank, canonical proof, task readiness, source revision | At most 100; no hidden sorting or silent feedback mutation. |
| `ExportValidationResult` | validator/rule versions, errors/warnings, per-query findings, identity checks, ready flag | Any required unresolved check means not ready. |
| `SubmissionPackage` | immutable CSV inventory/digests, ZIP digest/tree, validation result, provisional-rule version | Headerless task schemas; top-level `submission/`; reopen validation required. |
| `ArtifactReadiness` | dependency/module, `READY|PARTIAL|MISSING|INCOMPATIBLE`, roots, expected/observed coverage, schema/digests/provenance, diagnostics/time | Read-only; readiness validator never repairs or preprocesses. |
| `DegradedState` | dependency/capability, reason, affected actions, safe fallback, observed time | Visible and scoped; exact-frame degradation never satisfies final P0. |
| `EvaluationRun` | dataset/verdict source, prediction/config versions, official/internal metric results, completeness, benchmark/ablation/error/mock refs | No official-dataset-ready claim without valid ground truth/adjudication. |
| `OperationalTelemetry` | query/run/model/config IDs, branch statuses, latency, corrections, time-to-first-correct, validation/submission errors | No secrets or operator-approved answer rewriting. |
| `OperatorDraft` | sessions, feedback, approvals, TRAKE locks, baskets, UI preferences/shortcut bindings, revision/checksum | Atomic persistence; restore always revalidates. |
| `ConfigLock` | service/media roots, artifact manifests/digests, schema/model versions, environment profile, approval | Final live uses frozen compatible values; secrets referenced externally. |
| `BackupManifest` | WP13 mutable paths, checksums, timestamp, config lock, restore result | Upstream read-only artifacts are referenced, not copied into WP13 backup. |

Core transitions:

`query -> original results -> optional feedback snapshot -> inspected canonical frame -> basket guard -> task validation -> CSV -> ZIP revalidation -> human-controlled submission`

VQA adds `proposal -> edit -> explicit approval`; TRAKE adds `ordered slots -> lock/correct -> pre-basket validation`; every restored or handover-changed state returns to validation before ready.
