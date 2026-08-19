# E3 Research and Decisions

Authority order used here is official AIC 2026 competition PDF -> AIC2026 Final Pipeline -> AIC 2025 guide for provisional operational submission mechanics only -> current physical/runtime/source evidence -> derived WP13 planning documents. Evidence records current state; it does not override a higher-authority requirement.

## Authority-backed decisions

| Decision | Evidence and consequence |
|---|---|
| Separate target, current artifacts and final acceptance | The Final Pipeline defines the complete target. Current coverage limits tests, not product scope. Corrected handover triggers validation/rerun, not redesign. |
| Claim 1 is EXTERNAL ARTIFACT DEPENDENCY | TV4 points to the real WP03 `smoke-run-1`; four visual-model FAISS indexes exist, with confirmed coverage of 3/873 videos and 892/106,380 selected frames/vectors. Use it for current integration only; the corrected corpus-complete package is `HANDOVER PENDING`, and WP13 never runs WP03 preprocessing. |
| Claim 2 is HANDOVER PENDING, not ACTUALLY MISSING | WP04 producer source, modality contracts, evidence endpoints and reusable Range/original-frame/resolve semantics exist. Corrected OCR/ASR/Object/Metadata artifacts/indexes/evidence are pending from the owner. Implement consumer seams/degradation now; WP13 does not run or repair the producer. |
| E4-1 exact-frame foundation is CLOSED / ACCEPTED | Production `ExactFrameResolver`, canonical original identity, certified-anchor behavior, signed cumulative stepping, previous/current/next ORIGINAL frames, boundary behavior, proof rejection, live non-sample acceptance, TV4 `/exact-frame/neighbors` integration and automated tests were accepted. Remaining work is WP13 UI/state/basket integration and regression protection, not backend reconstruction. |
| Feedback workflow is P0; advanced model is optional | WP08 already preserves original query, reference identity, history/revisions and measures first-correct. Its stable four-model ranker requires benchmark provenance. Integrate supported workflow; do not make model availability a global release blocker. |
| Independent WP13 submission exporter | TV4 writes headers/extra fields and TRAKE JSON. Official task semantics plus provisional headerless CSV/ZIP rules require a fail-closed independent exporter/validator. |
| VQA approved answer is immutable submission state | Upstream normalization may occur before proposal. Once edited/confirmed, exporter performs CSV escaping only and never trims/translates/rewrites/normalizes. |
| Metric implementation and official-dataset readiness are separate | Formulas/goldens can be complete without official ground truth or semantic adjudication. Missing adjudication yields `INCOMPLETE`. |

## Accepted exact-frame state and residual handling

E4-1's bounded original-video decoding and canonical proof path is the accepted backend foundation. Its invariants remain mandatory: raw PTS/FPS/keyframe/proxy/UI/browser/seek-local ordinals never become submission identity, stale or conflicting proof fails closed, and a newly inspected neighbor is nonselectable until proof passes. WP13 must preserve those invariants in inspector, stepping and basket regressions.

The certification's bounded semantic sample and `VFR_NOT_LIVE_SAMPLED` note are accepted residual defense-in-depth risks and are not a current P0 implementation phase. Optional later hardening may expand samples without blocking the planned media/UI integration. No task may redesign WP09, repeat its synchronization, or build a persistent full-corpus replacement mapping.

## Current boundary findings

- TV4 endpoints include `/health`, `/kis/search`, `/vqa/answer`, `/trake/align` and accepted `/exact-frame/neighbors`; Feedback and browser-safe media/image endpoints remain CODE GAPs.
- TV4 health does not probe live dependencies. Fixture health is only fixture readiness.
- TV4 VQA evidence probe omits original question/query, flattens OCR/ASR/Object details and has an unsafe manual-review predicate. The rule fallback treats any nonempty evidence string as verified.
- The physical system contains 873 original MP4s plus corpus-scale keyframes, thumbnails and mappings. WP04 source already implements Range streaming, original-frame decode and timestamp/frame resolution. TV4 browser-safe registry/containment/Range/image transport remains a CODE GAP; original-video capability is not absent.
- WP08 tracked/runtime service hashes match for the inspected seam and supports original query, selected `CandidateId`, feedback events/history and revision control. Its model adapter is not assumed available through TV4.
- WP09 tracked -> runtime synchronization is complete: 34 tracked files verified identical, zero runtime missing and zero hash mismatch. It MUST NOT be repeated. The accepted TV4 exact/API tracked/runtime files were also inspected as aligned for the E4-1 seam; later TV4 release changes still require ordinary tracked-first review.

## Reuse

Reuse raw MP4, manifests, media/audio, frames/mappings/shots, keyframes/thumbnails, temporal selected-frame artifacts, current/future WP03 artifacts, WP04 service source/contracts/media semantics and future modality handover, WP08 service/contracts, the accepted WP09 exact-frame foundation, WP07/RRF, TV4 orchestration, official metrics and canonical selected anchors. Do not duplicate upstream-owned schemas or preprocessing.

## Rejected approaches

- Redesigning around three videos or empty WP04.
- Running WP03/WP04 preprocessing from WP13.
- Reopening accepted E4-1, repeating WP09 synchronization, corpus-wide startup decode or persistent replacement mapping.
- Raw PTS/FPS/browser time/proxy/keyframe/seek-local identity.
- Display-only neighbors for final P0.
- Directly summing incompatible raw retrieval scores.
- Object hard filter by default.
- Automatic VQA approval or exporter normalization.
- Numerical sorting as TRAKE semantic order.
- Treating the advanced feedback model as global P0.
- Trusting fixture/demo success as live contest readiness.

## Open decisions

None blocks implementation after independent document review. Operational API submission fallback remains conditional on an approved callable endpoint; existing TV4 retrieval/export utilities are not the approved contest exporter. WP13 CLI/package preparation is mandatory and actual Codabench upload remains human-controlled.
