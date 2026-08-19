# Tasks: Complete Contest-Ready WP13

**Rule**: Every open task is test/evidence first. `[P]` is safe parallel work. `Owner` names the work-package/source area, not a new authority. `Final-live` identifies a dependency that does not block implementation. Status lanes are **CAN IMPLEMENT NOW**, **WAIT FOR HANDOVER**, and **FINAL LIVE ACCEPTANCE**. Completed E4-1 tasks remain listed under their stable IDs as accepted history and are not rescheduled.

**Authority**: official AIC 2026 competition PDF -> AIC2026 Final Pipeline -> AIC 2025 provisional operational submission guide -> current physical/runtime/source evidence -> derived WP13 planning documents. No task may reduce a higher-authority requirement to match current code.

## Phase A - governance, contracts and readiness (CAN IMPLEMENT NOW)

- [ ] **T001 [P0] Governance** (Owner: TV5; Reqs: FR-001-005, FR-080) Reconcile authority assertions and machine-readable requirement/task/test map in `specs/...` and future `tests/traceability/`. Prereq: none. Test first: checker detects missing/orphan requirement and forbidden preprocessing task. Accept: every FR maps to task/test and no task runs upstream preprocessing. Final-live: none.
- [ ] **T002 [P0] Boundary goldens** (Owner: TV5/TV4; Reqs: FR-058-067) Capture actual TV4/WP08/WP09 request/response schemas and malformed/degraded fixtures in `tests/contract/`. Prereq: T001. Test first: schema-version/canonical-field/unknown-field cases fail against current gaps. Accept: KIS, Feedback, VQA, TRAKE, evidence and health seams are explicit. Final-live: none.
- [ ] **T003 [P] [P0] Readiness validator tests** (Owner: TV5; Reqs: FR-073-075) Add fixtures/goldens for `READY|PARTIAL|HANDOVER PENDING|CODE GAP|INCOMPATIBLE|ACTUALLY MISSING`, CLI diagnostics and non-mutation in `tests/unit/test_artifact_readiness.py`. Prereq: T001. Accept: current WP03 is `PARTIAL`; corrected WP04 modality delivery is `HANDOVER PENDING`; absent TV4 transport over an existing capability is `CODE GAP`; corrupt schema/digest is `INCOMPATIBLE`. Final-live: none.
- [ ] **T004 [P0] Readiness validator** (Owner: TV5; Reqs: FR-073-075) Implement read-only manifest/schema/digest/index-map/count/coverage/linkage/provenance checks in `tv5/readiness/` and CLI/status adapter. Prereq: T003. Accept: derives expected coverage from registries where practical, distinguishes handover/data/source/adapter/UI state, never preprocesses/repairs, emits actionable report. Final-live: corrected Claim 1/2 handovers for `READY` acceptance.

## Phase B - accepted E4-1 exact-frame foundation (CLOSED / ACCEPTED; historical IDs)

- [x] **T005 [P0] Resolver proof fixtures** (Owner: WP09 tracked source; Reqs: FR-068-071) Completed in E4-1. Evidence: `TV2/WP09/tests/test_production_resolver.py`, `test_canonical_identity_proof.py` and `test_run_certified_resolution.py`; accepted review includes forged/nonselectable proof rejection and live non-sample video acceptance. The bounded semantic certification sample and `VFR_NOT_LIVE_SAMPLED` are accepted non-blocking residual risks.
- [x] **T006 [P0] Production resolver** (Owner: WP09 tracked source; Reqs: FR-068-071) Completed in E4-1. Evidence: production `ExactFrameResolver` and certified canonical identity path in `TV2/WP09/src/wp09/mapping.py`; unresolved/conflicting proof fails closed. Do not rebuild.
- [x] **T007 [P0] Consecutive-neighbor tests** (Owner: WP09; Reqs: FR-068-071) Completed in E4-1. Evidence: `TV2/WP09/tests/test_exact_neighbors.py` covers previous/current/next ORIGINAL frames, repeated stepping and boundaries under the accepted scope.
- [x] **T008 [P0] Consecutive-neighbor service** (Owner: WP09; Reqs: FR-068-071) Completed in E4-1. Evidence: accepted certified-anchor and signed cumulative-step service/contracts/cache behavior with canonical selectable proof and no persistent corpus replacement index.
- [x] **T009 [P0] WP09 integration regressions** (Owner: WP09; Reqs: FR-068-071) Completed in E4-1. Evidence: accepted automated WP09 policy/cache/provenance regressions preserve the canonical coarse candidate and reject unproved neighbor selection.

## Phase C - TV4 integration corrections and media (CAN IMPLEMENT NOW)

- [x] **T010 [P] [P0] TV4 exact-frame tests** (Owner: TV4 tracked source; Reqs: FR-068-072) Completed in E4-1. Evidence: `tv4/tests/test_wp09_integration.py`, `test_exact_identity.py` and API regressions cover canonical replacement, stale/forged/nonselectable rejection and accepted media identity behavior.
- [x] **T011 [P0] TV4 WP09 integration repair** (Owner: TV4 tracked source; Reqs: FR-068-071) Completed in E4-1. Evidence: tracked TV4 adapter/client/API use resolver-proven identities and preserve/degrade the canonical anchor on failure. This task does not include the still-open browser media transport.
- [x] **T012 [P0] Exact-neighbor API contract** (Owner: TV4; Reqs: FR-068-071) Completed in E4-1. Evidence: `POST /exact-frame/neighbors` exposes certified-anchor signed cumulative stepping, ORIGINAL-frame neighbors/boundaries, selectable proof/provenance and fail-closed invalid-identity handling. WP13 consumption tests remain in downstream UI/basket tasks.
- [ ] **T013 [P] [P0] Existing media boundary characterization and security goldens** (Owner: TV4/TV5; Reqs: FR-022-026, FR-072) Characterize WP04's existing Range streaming, original-frame JPEG and timestamp/frame resolution semantics, then add TV4/WP13 goldens for HEAD/GET/206/416, containment, traversal/symlink, unknown video, allowed extension, identity headers, read-only behavior and proxy resolution. Prereq: T002. Accept: tests distinguish the existing upstream capability from the TV4 CODE GAP and never derive identity from playback. Final-live: target media mount.
- [ ] **T014 [P0] Minimal safe TV4 media/image adapter** (Owner: TV4/TV5; Reqs: FR-022-026, FR-072) Reuse/wrap the proven WP04 semantics behind TV4 with configured authoritative registry/root resolution, contained byte-range video and original-frame/keyframe/thumbnail browser URLs; UI opens canonical timestamps only. Prereq: T013. Accept: original source remains read-only, contained and seekable; response identity is authoritative; canonical IDs come only from upstream/exact service. Final-live: target mount validation.
- [ ] **T015 [P] [P0] Rich evidence/VQA tests** (Owner: TV4; Reqs: FR-009-016, FR-061, FR-064-066) Test original query/question propagation, OCR bbox, ASR timing/context, Object bbox/crop, multi-frame refs, empty evidence, verifier, one controlled retry, abstain/manual predicate. Prereq: T002. Accept: current flattened/unsafe implementation fails. Final-live: WP04/VLM availability only for respective live cases.
- [ ] **T016 [P0] TV4 evidence and VQA repair** (Owner: TV4; Reqs: FR-009-016, FR-061, FR-064-066) Extend contracts/client/wiring in `contracts.py`, `wp11_vqa.py`, `api.py`; retain pre-approval normalization but return advisory proposal/status. Prereq: T015. Accept: empty evidence never confident; weak/unavailable VLM manual; evidence retains provenance. Final-live: corrected WP04 and approved VLM/verifier.
- [ ] **T017 [P] [P0] Dependency-health tests** (Owner: TV4/TV5; Reqs: FR-047-049, FR-073) Test probes for WP03, each WP04 branch/index, WP08, WP09, VLM/verifier and media. Prereq: T002. Accept: process-up/config-load alone is not `READY`; fixture labeled. Final-live: live services.
- [ ] **T018 [P0] Dependency health/degraded API** (Owner: TV4; Reqs: FR-047-049, FR-073) Implement component readiness and capability impact in `api.py`, config/adapters/fixtures. Prereq: T017. Accept: honest scoped status and safe fallbacks. Final-live: all live probes.
- [ ] **T019 [P] [P0] Feedback seam tests** (Owner: WP08/TV4; Reqs: FR-059-060) Test original query/reference/text/history/revision/refined state/reset/no basket mutation/unavailable status against actual WP08 contracts. Prereq: T002. Accept: no invented WP08 behavior; advanced model absence is scoped degradation. Final-live: benchmark-approved model only if selected.
- [ ] **T020 [P0] TV4 Feedback integration** (Owner: TV4; Reqs: FR-059-060) Add supported WP08 adapter/API/fixtures and canonical validation in tracked TV4. Prereq: T019. Accept: deterministic current seam or explicit unavailable; original results remain retrievable. Final-live: corrected WP03 for corpus-wide live feedback.
- [x] **T021 [P0] WP09 tracked/runtime synchronization** (Owner: WP09; Reqs: FR-068-072) Completed and accepted. Evidence: `D:\aic226\WP09_TRACKED_RUNTIME_SYNC_REPORT.txt` records `tv5/TV2/WP09` -> `tv2_1/WP09`, 34 tracked files verified identical, 0 runtime missing and 0 hash mismatch. Do not repeat this synchronization. Future TV4/WP13 release-file synchronization, if needed after their own open tasks, follows normal tracked-first review and is not a reason to rerun WP09 sync.

## Phase D - WP13 application foundation (CAN IMPLEMENT NOW)

- [ ] **T022 [P] [P0] Shell/state tests** (Owner: TV5; Reqs: FR-047-050, FR-078) Add fixture/current-partial/final-live config, atomic draft, restore-revalidation and status-view tests in `tests/unit/` and `tests/integration/`. Prereq: T002. Accept: deterministic state and visible modes. Final-live: none.
- [ ] **T023 [P0] WP13 shell/state** (Owner: TV5; Reqs: FR-047-050, FR-078) Implement app/config/typed clients/domain persistence/status shell in `tv5/`. Prereq: T022. Accept: only WP13 mutable state is writable; health visible; restore invalidates readiness. Final-live: none.
- [ ] **T024 [P] [P0] Telemetry tests** (Owner: TV5; Reqs: FR-058, FR-076-077) Test query/run/model/config/branch/latency/correction/time-first-correct/validation-error events and secret redaction. Prereq: T022. Accept: deterministic schema/provenance. Final-live: none.
- [ ] **T025 [P0] Operational telemetry** (Owner: TV5; Reqs: FR-058, FR-076-077) Implement bounded structured telemetry/report adapters in `tv5/telemetry/`. Prereq: T024. Accept: reports support benchmark/error/mock workflow without upstream job ownership. Final-live: none.

## Phase E - operator workflows (CAN IMPLEMENT NOW)

- [x] **T026 [P] [P0] KIS/Visual tests** (Owner: TV5; Reqs: FR-006-008, FR-058, FR-063-066) Test text query, <=100 continuous rank, Visual/FAISS provenance, diversity, empty/degraded/dense fallback, exact correction and selection. Prereq: T023. Accept: deterministic fixture and current WP03 cases. Final-live: corrected WP03 for corpus coverage.
- [x] **T027 [P0] KIS workflow/UI** (Owner: TV5; Reqs: FR-006-008, FR-058, FR-063-066) Implement KIS mode/grid/inspection actions/adapters. Prereq: T026,T012,T014. Accept: operator selects only canonical candidate/neighbor and logs run/config/latency. Final-live: corrected WP03.
- [x] **T028 [P] [P0] Feedback state/UI tests** (Owner: TV5; Reqs: FR-059-060, FR-067) Test canonical reference, original query/text/history, separate snapshots, reset, no basket mutation, candidate revalidation and unavailable WP08. Prereq: T023. Accept: deterministic. Final-live: corrected WP03 for full coverage.
- [x] **T029 [P0] Feedback workflow/UI** (Owner: TV5; Reqs: FR-059-060, FR-067) Implement reference selection, history/refined view/reset through TV4 WP08 seam. Prereq: T020,T028. Accept: workflow usable with supported current capability; advanced model gate visible/scoped. Final-live: selected model benchmark if applicable.
- [x] **T030 [P] [P0] VQA tests** (Owner: TV5; Reqs: FR-009-016, FR-061, FR-066-067) Test empty/weak evidence, OCR/ASR/Object/multiframe paths, proposal/confidence, retry limit, exact correction, edit/confirm, exact approved answer preservation and VLM degradation. Prereq: T023. Accept: no auto-confirm. Final-live: corrected WP04/VLM for respective cases.
- [x] **T031 [P0] VQA workflow/UI** (Owner: TV5; Reqs: FR-009-016, FR-061, FR-066-067) Implement evidence panels, proposal/manual state, editable approval and canonical selection. Prereq: T016,T030,T014. Accept: approved text becomes immutable submission state. Final-live: corrected WP04 and approved VLM/verifier.
- [x] **T032 [P] [P0] TRAKE tests** (Owner: TV5; Reqs: FR-017-021, FR-062, FR-067) Test ordered events/count, hypotheses/video, semantic order, wrong-video semantics, timeline, locks/unlock, manual correction, exact event frame, no accidental reorder and pre-basket rejection. Prereq: T023. Accept: exactly N positions; numerical sort never redefines order. Final-live: corrected upstream coverage.
- [x] **T033 [P0] TRAKE workflow/UI** (Owner: TV5; Reqs: FR-017-021, FR-062, FR-067) Implement immutable event slots/timeline/hypotheses/locks/corrections/validation. Prereq: T012,T032,T014. Accept: only complete canonical chain enters basket. Final-live: corrected WP03/WP04.
- [ ] **T034 [P] [P0] Evidence rendering tests** (Owner: TV5; Reqs: FR-064-067) Test OCR overlays, ASR timing/context, Object bbox/crops, Metadata, selected frames and source/model/run provenance with missing branches. Prereq: T023. Accept: provenance not flattened; degradation visible. Final-live: corrected WP04.
- [ ] **T035 [P0] Evidence/provenance UI** (Owner: TV5; Reqs: FR-064-067) Implement typed renderers and safe overlays. Prereq: T034. Accept: available evidence displayed accurately; absent data not fabricated. Final-live: corrected WP04.
- [ ] **T036 [P] [P0] Keyboard/operator tests** (Owner: TV5; Reqs: FR-067) Define/test documented shortcuts for mode/search/grid/player/step/reference/confirm/lock/basket/reset with focus guards and no destructive ambiguity. Prereq: T027,T029,T031,T033. Accept: automated state tests plus manual checklist. Final-live: manual target verification.
- [ ] **T037 [P0] Keyboard shortcuts** (Owner: TV5; Reqs: FR-067) Implement shortcut registry/help and focus-safe handlers. Prereq: T036. Accept: no shortcut bypasses confirmation/canonical validation/order locks. Final-live: operator acceptance.

## Phase F - basket, submission and evaluation (CAN IMPLEMENT NOW)

- [ ] **T038 [P] [P0] Basket guard tests** (Owner: TV5; Reqs: FR-027-029, FR-036-039, FR-071) Test 0/100/101, visible rank, no hidden sort, canonical proof, refined candidates, exact neighbors, VQA approval and TRAKE validity. Prereq: T023. Accept: invalid entry fails closed. Final-live: none.
- [ ] **T039 [P0] Submission basket** (Owner: TV5; Reqs: FR-027-029, FR-036-039, FR-071) Implement query-scoped ordered basket/readiness audit. Prereq: T038. Accept: all workflows share guards and feedback never mutates basket. Final-live: none.
- [ ] **T040 [P] [P0] CSV/export goldens** (Owner: TV5; Reqs: FR-030-039, FR-057) Add headerless KIS/Q&A/TRAKE, <=100, integer/`.mp4`, exact answer roundtrip, TRAKE N/order, filename and provisional-version tests. Prereq: T038. Accept: current TV4 exporter shown incompatible; valid/invalid goldens deterministic. Final-live: re-review on official 2026 guide.
- [ ] **T041 [P0] CSV exporter/validator** (Owner: TV5; Reqs: FR-030-039, FR-057) Implement independent standards-compliant serializer/parser/validator in `tv5/submission/`. Prereq: T039,T040. Accept: approved answer unchanged except escaping; all detectable errors reported; fail closed. Final-live: official guide review.
- [ ] **T042 [P0] ZIP/package tests and implementation** (Owner: TV5; Reqs: FR-040-042, FR-078) Test traversal, root CSV, missing/duplicate/unexpected/malformed files and reopen validation; implement top-level `submission/` ZIP. Prereq: T041. Accept: immutable digest/report and no upload. Final-live: provisional rules confirmed/reviewed.
- [ ] **T043 [P] [P0] CLI/API fallback tests** (Owner: TV5; Reqs: FR-051, FR-078) Test non-UI validate/export/package and failure behavior; characterize any approved API seam. Prereq: T041. Accept: CLI works without UI; API marked unavailable unless real approved endpoint exists. Final-live: none.
- [ ] **T044 [P0] CLI/API fallback** (Owner: TV5; Reqs: FR-051, FR-078) Implement CLI preparation/validation; implement API adapter only if T043 proves approved contract. Prereq: T042,T043. Accept: never auto-uploads. Final-live: target rehearsal.
- [ ] **T045 [P] [P0] Official/internal metric tests** (Owner: TV5; Reqs: FR-043-046, FR-076-077) Add organizer KIS/VQA/TRAKE/R@k/Final=0.74 goldens, Hit@K, alignment, latency/error and missing-adjudication `INCOMPLETE`. Prereq: none. Accept: exact formulas; no exact-string substitute. Final-live: official ground truth for dataset-ready status.
- [ ] **T046 [P0] Metric/report engine** (Owner: TV5; Reqs: FR-043-046, FR-076-077) Implement metrics, benchmark/ablation/error/mock report schema and UI/CLI adapter. Prereq: T045,T025. Accept: metric implementation ready independently of dataset readiness. Final-live: valid ground truth/adjudication.
- [ ] **T047 [P] [P0] Preprocessing report ingestion tests** (Owner: TV5; Reqs: FR-076-077) Test validated upstream throughput/storage report ingestion, schema/provenance/missing/incompatible state. Prereq: T004. Accept: no preprocessing command invoked. Final-live: approved reports.
- [ ] **T048 [P0] Preprocessing report ingestion** (Owner: TV5; Reqs: FR-076-077) Implement read-only report adapter/display. Prereq: T047,T046. Accept: source/run provenance and explicit unavailable status. Final-live: accepted reports.

## Phase G - fixture, deployment and current integration (CAN IMPLEMENT NOW)

- [ ] **T049 [P] [P0] Complete fixture/degraded suite** (Owner: TV5/TV4; Reqs: FR-047-050, FR-058-067) Add deterministic canonical fixtures for KIS/Feedback/VQA/TRAKE/evidence/exact neighbors and each dependency failure. Prereq: T012,T016,T018,T020,T039,T046. Accept: fixture/live semantics identical and fixture label explicit. Final-live: none.
- [ ] **T050 [P0] Current-artifact integration** (Owner: TV5; Reqs: FR-073-075) Run validator, current 3-video WP03 KIS/Feedback where supported, accepted exact-frame consumption/media, WP04 `HANDOVER PENDING` plus scoped degraded behavior, all fixture workflows, export/metrics/telemetry; record results. Prereq: T021,T049. Accept: supported checks pass and limitations remain accurately classified as `PARTIAL`, `HANDOVER PENDING` or `CODE GAP`; no existing capability is called missing solely for lack of a TV4 endpoint. Final-live: none.
- [ ] **T051 [P] [P0] Compose/config-lock tests** (Owner: TV5+TV1 support; Reqs: FR-052-055, FR-078-079) Test read-only mounts, external upstream URLs, mutable persistence, probes, config digest/secret exclusion and fresh start. Prereq: T023,T044,T049. Accept: no preprocessing/build of upstream assets. Final-live: target host.
- [ ] **T052 [P0] Docker Compose/config lock** (Owner: TV5+TV1 support; Reqs: FR-052-055, FR-078-079) Implement WP13 Compose/env/config lock/health startup. Prereq: T051. Accept: fixture/current modes start reproducibly; upstream mounts read-only. Final-live: frozen corrected artifacts/config.
- [ ] **T053 [P] [P0] Backup/restore tests** (Owner: TV5; Reqs: FR-050, FR-054-055, FR-078-079) Test backup manifest/checksums, interrupted write, restore/revalidation and exclusion of upstream artifacts/secrets. Prereq: T023. Accept: restored state not ready until revalidated. Final-live: target rehearsal.
- [ ] **T054 [P0] Backup/restore implementation** (Owner: TV5; Reqs: FR-050, FR-054-055, FR-078-079) Implement scripts/docs for WP13 mutable state/config lock. Prereq: T053,T052. Accept: repeatable recovery with audit. Final-live: target pass.
- [ ] **T055 [P0] RUN_BOOK/operator handoff** (Owner: TV5+TV1 support; Reqs: FR-051-055, FR-078-079) Write `RUN_BOOK.md` for three modes, service order, readiness/degradation, exact gate, submission fallbacks, telemetry, shutdown/recovery and no preprocessing. Prereq: T044,T050,T052,T054. Test first: non-owner dry-run checklist. Accept: another member can operate fixture/current partial. Final-live: final mode and target evidence.

## Phase H1 - external handover acceptance (WAIT FOR HANDOVER)

- [ ] **T056 [P0] Corrected WP03 acceptance** (Owner: external handover + TV5 validator; Reqs: FR-063, FR-074) Read-only validate schema/digests/index-map/vector/video/selected-frame coverage/canonical mapping/run; freeze approved root/config. Prereq: T004; External: Claim 1 handover. Accept: `READY`, expected corpus coverage from authoritative registries. No repair/preprocess.
- [ ] **T057 [P0] Corrected WP04 acceptance** (Owner: external handover + TV5 validator; Reqs: FR-064, FR-075) Read-only validate handed-over OCR/ASR/Object/Metadata records, linkage/timing/evidence/provenance/indexes; freeze. Prereq: T004; External: Claim 2 corrected modality handover. Accept: required branches `READY`. Producer source/contracts already exist; no WP13 repair/preprocess.

## Phase H2 - final live acceptance (FINAL LIVE ACCEPTANCE)
- [ ] **T058 [P0] Full live integration** (Owner: team; Reqs: FR-058-079) Rerun all modality, RRF, KIS/Feedback/VQA/TRAKE, exact-frame, media, health, submission, evaluation and telemetry integrations without architecture change. Prereq: T055,T056,T057. Accept: all applicable live contracts pass.
- [ ] **T059 [P0] Live E2E and manual UI** (Owner: TV5; Reqs: FR-067, FR-079) Execute all three task journeys plus Feedback, neighbors, evidence, keyboard, basket, CSV/ZIP/CLI, degraded/recovery; measure latency/time-first-correct/error. Prereq: T058. Accept: no known P0 and manual evidence recorded.
- [ ] **T060 [P0] Mock competitions** (Owner: team; Reqs: FR-056, FR-077, FR-079) Run Benchmark -> Ablation -> Error Analysis -> Mock -> Iterate until three consecutive mocks have no known P0. Prereq: T059,T046,T048. Accept: three signed reports/config IDs; reset count after P0.
- [ ] **T061 [P0] Target-machine acceptance/release freeze** (Owner: TV5+TV1 support; Reqs: FR-052-055, FR-078-079) Non-owner performs fresh start, readiness/health, live task flows, exact-neighbor proof sample, golden package, CLI fallback, backup/restore and config/artifact freeze. Prereq: T060. Accept: cross-review, no owner-only knowledge, stable tag/commit prepared but commit/push only under separate authorization.

## Critical path and parallel work

Critical path from the reconciled current state: `T001/T002/T003 -> T004/T013 -> T014 -> T022/T023 -> T026/T027 -> T019/T020/T028/T029 -> T015/T016/T030/T031 -> T032/T033 -> T038/T039/T040/T041/T042/T044 -> T045/T046/T047/T048 -> T049/T050/T052/T054/T055 -> T056/T057 -> T058 -> T059 -> T060 -> T061`. T005-T012 and T021 are accepted completed foundations, not future prerequisites to re-execute.

While Claim 1/2 are pending, the open portions of T001-T055 can proceed subject only to their listed prerequisites. T056-T057 wait for their respective handovers; T058-T061 are final-live acceptance. No task runs WP03/WP04 preprocessing, regenerates embeddings/indexes/mappings, repeats WP09 synchronization or creates a persistent full-corpus frame-index artifact.

## Reconciled implementation sequence

1. Governance, boundary goldens and readiness foundation: T001-T004.
2. Media boundary characterization/regression goldens: T013.
3. Safe TV4 media/image transport: T014.
4. WP13 fixture-first shell and KIS vertical slice: T022-T027.
5. Feedback: T019-T020 and T028-T029.
6. Safe VQA: T015-T016 and T030-T031.
7. TRAKE: T032-T033.
8. Submission pipeline: T038-T044.
9. Evaluation and operations: T024-T025 and T045-T055.
10. Corrected WP03/WP04 handover validation: T056-T057.
11. Final live E2E, mocks and release: T058-T061.

## Requirement-to-test summary

| Capability / requirements | Implementation tasks | Primary test/acceptance path |
|---|---|---|
| KIS FR-006-008,058,063-066 | T026-T027 | KIS contract/fixture/current/live E2E |
| Feedback FR-059-060 | T019-T020,T028-T029 | WP08 contract, snapshot/reset/basket invariants |
| VQA FR-009-016,061 | T015-T016,T030-T031 | empty/weak/OCR/ASR/Object/retry/edit/confirm/export |
| TRAKE FR-017-021,062 | T032-T033 | event count/order/locks/correction/exact/export |
| Exact/media FR-022-026,068-072 | T005-T014 | resolver proof, neighbor API, media security, live sample |
| UI/evidence/shortcuts FR-064-067 | T034-T037 | renderer/interaction tests plus manual UI |
| Basket/submission FR-027-042,051,057,078 | T038-T044 | canonical guards, CSV/ZIP goldens, CLI/API characterization |
| Evaluation FR-043-046,076-077 | T024-T025,T045-T048 | organizer goldens, completeness, report ingestion |
| Fixture/degraded/readiness FR-047-050,073-075 | T003-T004,T017-T018,T049-T050 | classified status and dependency-failure matrix |
| Deployment/handoff FR-052-056,078-080 | T051-T061 | Compose, recovery, runbook, handovers, live E2E, mocks, target |
