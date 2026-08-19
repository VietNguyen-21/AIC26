# WP13 System Reconciliation and Integration Matrix

Generated 2026-08-18. This is a read-only architecture/integration finding, not an implementation or contract change.

## Executive verdict

WP13 is **not contest-ready**, but the physical system is much closer to an integrable backend than a TV4-endpoint-only reading suggests. The 873 original MP4s, corpus-scale `run_v1_batch1` keyframes/thumbnails/mappings, real WP03 embeddings and four FAISS indexes, WP04 producer/contracts/media/evidence APIs, WP08 state machine, WP09 exact-frame framework, and TV4 KIS/RRF/VQA/TRAKE orchestration all exist. Most unresolved items are **CODE GAP** at the TV4/WP13 transport, state, UI, submission, evaluation, and operations layers. They are not preprocessing gaps.

Final-live readiness is gated by (1) the corrected corpus-complete WP03 handover, (2) the corrected WP04 OCR/ASR/Object/Metadata handover, (3) live proof of the newly staged/synchronized WP09 certified exact-neighbor path, including its stated VFR limitation, and (4) the still-absent WP13 product, exporter, evaluator, and deployment package.

No capability below is called `ACTUALLY MISSING` merely because TV4 lacks an endpoint. In particular, original-video byte-range streaming and original-frame decoding already exist in the WP04 service source; keyframes, thumbnails, mappings, visual indexes, and feedback code also physically exist.

## Authority and interpretation

Priority is: AIC 2026 official PDF -> Final Pipeline -> AIC 2025 submission guide for provisional mechanics only -> current WP13 derived documents -> tracked implementation -> runtime evidence. The official 2026 PDF defines KIS, VQA and TRAKE answer semantics, up to 100 answers/query, task R-Score, R@1/5/20/50/100 and Final Score. The 2025 guide is used only for provisional CSV/query-name/ZIP/manual-upload mechanics.

Status vocabulary in this report is exactly `READY`, `PARTIAL`, `HANDOVER PENDING`, `CODE GAP`, `INCOMPATIBLE`, or `ACTUALLY MISSING`. `READY` is scoped to the acceptance level stated in the row; it never means overall contest readiness.

## Evidence registry

The matrix uses these exact evidence anchors to remain readable.

| ID | Exact evidence |
|---|---|
| E01 | `D:\aic226\references\competition\Thong_Tin_Vong_So_Tuyen_AIC_2026.pdf`, sections 1.1-1.3 and 2.1-2.2 |
| E02 | `D:\aic226\references\competition\AIC2025_Huong_Dan_Nop_Bai_So_Tuyen_REFERENCE.pdf`, query naming, CSV, packaging and Codabench sections |
| E03 | `D:\aic226\references\architecture\AIC2026_Pipeline_Final.md`, sections 2-5, 8, 10-13 |
| E04 | `D:\aic226\tv1\data\raw\video` (873 direct `.mp4` files); `D:\aic226\tv1\data\runs\run_v1_batch1\manifest\corpus_manifest.json` (873 accepted records) |
| E05 | `D:\aic226\tv1\data\runs\run_v1_batch1\frames.parquet`; `mappings\` (873); `keyframes\` and `thumbnails\` (106,380 each); `shots\`; `temporal\` |
| E06 | `D:\aic226\tv1\wp06_api_server.py::get_manifest,get_frames_by_video,get_keyframe_image,validate_run`; no video stream/thumbnail route |
| E07 | `D:\aic226\tv1tv3\TV1_TV3_WP04\src\aic2026\api.py::stream_video,original_frame,resolve,temporal_window` (Range-capable original media and frame decode) |
| E08 | Same `api.py::ocr_endpoint,ocr_detections,ocr_crop,asr_endpoint,asr_segments,asr_context,object_endpoint,object_detections,metadata_endpoint,metadata_records,evidence_catalog_status` |
| E09 | `D:\aic226\tv1tv3\TV1_TV3_WP04\src\aic2026\contracts.py::OCRDetection,ASRSegment,ObjectDetection,MetadataRecord,SearchCandidate,TextIndexManifest` |
| E10 | `D:\aic226\tv1tv3\TV1_TV3_WP04\data\runs` (current run root has no completed modality artifacts); corrected handover explicitly pending |
| E11 | `D:\aic226\tv2_1\WP03\artifacts\smoke-run-1\manifests\{beit3,bge_vl,metaclip2,perception}.json` (892 vectors/model, `preprocess_run_id=run_v1_batch1`) |
| E12 | `D:\aic226\tv2_1\WP03\artifacts\smoke-run-1\indexes\*.faiss`, `embedding_maps\*.parquet`, `embeddings\`; four real indexes and shards |
| E13 | `D:\aic226\tv5\TV2\WP03\src\wp03\cli.py::_search`; `search.py::search_visual`; `fusion.py::fuse_rrf`; `feedback_pool.py::build_feedback_pool` |
| E14 | `D:\aic226\tv5\TV2\WP08\src\wp08\contracts.py::CandidateId,SessionPool,SessionView,StableFeedbackConfig`; `service.py::FeedbackSessions`; `README.md` |
| E15 | `D:\aic226\tv5\TV2\WP09\src\wp09\mapping.py::ExactFrameResolver,ExactFrameResolution,MappedVideoDecoder`; `cli.py::neighbors`; `certification.py::RunCertification` |
| E16 | `D:\aic226\tv5\TV2\WP09\configs\certifications\run_v1_batch1.json`: 4 videos/12 anchors, `CERTIFIED`, limitation `VFR_NOT_LIVE_SAMPLED` |
| E17 | `D:\aic226\WP09_TRACKED_RUNTIME_SYNC_REPORT.txt`: all 34 Git-tracked WP09 files identical in `D:\aic226\tv2_1\WP09`, zero missing/mismatch |
| E18 | `D:\aic226\tv5\tv4\src\tv4\api.py::health,kis_search,vqa_answer,trake_align,exact_frame_neighbors` |
| E19 | `D:\aic226\tv5\tv4\src\tv4\wp07_router.py`; `wp10_fusion.py::reciprocal_rank_fusion`; `kis_pipeline.py::run_kis_query`; `trake_pipeline.py::run_trake_query` |
| E20 | `D:\aic226\tv5\tv4\src\tv4\clients\tv2_visual_client.py`; `tv3_client.py`; `tv2_refine_client.py`; `media_identity.py::resolve_original_media_path` |
| E21 | `D:\aic226\tv5\tv4\src\tv4\wp11_vqa.py::build_evidence_pack,answer_query,RuleBasedFallbackEngine` |
| E22 | `D:\aic226\tv5\tv4\src\tv4\wp12_trake.py::align_dp,align_greedy`; `contracts.py::TrakeHypothesis` |
| E23 | `D:\aic226\tv5\tv4\src\tv4\submission.py::write_kis_csv,write_qa_csv,write_trake_json`; emits headers/extra columns and TRAKE JSON |
| E24 | `D:\aic226\tv5\tv4\src\tv4\fixtures.py`; fixtures cover KIS/VQA/TRAKE/exact-neighbor only and exact neighbors are intentionally nonselectable |
| E25 | `D:\aic226\tv5\TV2\WP09\src\wp09\benchmark.py`; `D:\aic226\tv5\TV2\WP08\src\wp08\service.py::record_correct,feedback_metrics`; `D:\aic226\tv5\TV1_TV3_WP04\src\aic2026\benchmarking.py` |
| E26 | `D:\aic226\tv5\specs\001-contest-ready-wp13\{spec.md,plan.md,tasks.md,research.md,data-model.md,contracts\wp13-boundaries.md,quickstart.md}` |
| E27 | `D:\aic226\tv5\tv5` is absent; no WP13 UI/evaluation/submission/deployment source exists |
| E28 | Direct hashes: tracked/runtime TV4 exact/API/config files inspected are identical; `src\tv4\submission.py` differs between `D:\aic226\tv5\tv4` and `D:\aic226\tv4`, and both formats are contest-incompatible |
| E29 | `D:\aic226\AIC226_DEEP_ARCHITECTURE_INVENTORY.txt`; `AIC226_GLOBAL_ROOT_DEEP_PROBE.txt`; `WP03_WP08_DEEP_PROBE.txt` (its `FILES: 0` bug ignored and contradicted by direct inspection) |

## Full integration matrix

Every row follows the required 18-field schema. “Impl” and “runtime” distinguish tracked intent from deployed evidence. “Path” is always TV4-facing unless the row explicitly describes an upstream-only acceptance level.

### A. Query and retrieval

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KIS query/search | E01/E03 | WP07/10 TV4; UI TV5 | WP03 smoke + raw corpus | `SearchCandidate` -> WP02 identity | Router, clients, RRF, KIS pipeline | TV4 runtime matches inspected path | `POST /kis/search` | TV4 API -> WP13 | PARTIAL | HIGH | Works only at current visual coverage; missing honest branch status and UI | TV4/TV5 | Preserve schema/provenance; add capability status and UI slice | WP03/WP04 final data | Deterministic KIS fixture/dense-only | <=100 continuous canonical candidates; current smoke E2E; final corpus rerun | E11-E13,E18-E20,E24 |
| Query parser/router | E03 WP07 | WP07 TV4 | None required | `SearchRequest` | Rule cues + TRAKE split | Present | Internal Python contract | `/kis`,`/vqa`,`/trake` | PARTIAL | HIGH | No confidence, explicit filters policy, low-confidence multi-route or schema-validated LLM option | TV4 | Extend deterministic decision/provenance and tests; keep rule fallback | None | Rule fallback | visual/OCR/ASR/mixed/temporal/event goldens | E19 |
| Multimodal fusion + RRF | E03 WP07; invariant 12 | WP07/10 TV4 | Ranked branch lists | video/time bucket -> canonical candidate | Standard RRF, dedup, diversity, object soft | Present | Internal `fuse_kis` | Via task endpoints | READY | HIGH | No code gap in baseline algorithm; live value awaits branches | TV4 for regressions | Retain raw ranks/scores/provenance; do not sum raw scores | WP04 for final multimodal | Empty branches tolerated | RRF goldens; branch failure does not stop dense | E19 |
| WP03 visual retrieval / FAISS | E03 WP03 | WP03 TV2 | 4 indexes/maps/shards | `EmbeddingMapRecord` -> frame map | Search CLI, four-model late RRF | Real smoke artifacts | `python -m wp03 search` | TV4 subprocess client | READY | HIGH | Ready for smoke-scope integration, not corpus acceptance | TV2 | Consume, validate, do not rebuild | Corrected corpus handover | Current 3-video smoke | deterministic index-map counts and canonical candidates | E11-E13,E20 |
| Current visual artifact readiness | Final live gate + handover fact | WP03 TV2 | 892 vectors/model vs 106,380 selected frames; 3/873 videos | `run_v1_batch1` | Validators/inspect CLI exist | Artifacts real | manifests/digests/CLI | TV4 configured to smoke root | PARTIAL | HIGH | Coverage is intentionally smoke/partial | External WP03 owner | Read-only readiness report; keep limited integration label | Yes | Use supported videos only | schema/digest/index-map pass; report observed/expected coverage | E05,E11,E12,E29 |
| Future corrected WP03 handover | E03 G1/G4 | WP03 owner -> TV5 accept | Not yet delivered | Same run/mapping contract | Consumer code already general | Pending | Existing CLI/manifest contract | Config swap, no redesign | HANDOVER PENDING | HIGH | Corpus-complete validated visual/vector package pending | WP03 owner; TV5 validator | Validate/freeze roots, digests, coverage, model/run compatibility | Yes | Smoke remains available | expected corpus coverage, index ntotal=map count, live KIS/Feedback rerun | E03,E11-E13,E26 |

### B. Visual inspection and media

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Top-100 candidate rendering | E03 WP13 UI | TV5 | Candidate payloads/fixtures | Candidate identity | None | None | TV4 task APIs | API -> grid | CODE GAP | HIGH | WP13 application root absent | TV5 | Build virtualized, rank-visible grid and state tests | Final coverage only | Fixtures | 100 items usable; empty/error/degraded states | E18,E24,E27 |
| Keyframe image | E03 WP02/WP13 | TV1 asset; TV4 transport; TV5 UI | 106,380 JPGs | `frames.parquet.keyframe_path` | TV1 image route/client URL | TV1 service source exists | `/keyframe-image/...` | Must remain behind approved boundary | CODE GAP | HIGH | TV4 has no safe image proxy/typed URL contract | TV4/TV5 | Add contained read-only adapter/proxy | None | Fixture image | correct image and canonical metadata; traversal rejection | E05,E06,E20 |
| Thumbnail image | E03 WP02/WP13 | TV1 asset; TV4/TV5 | 106,380 thumbnails | `FrameRecord.thumbnail_path` | Asset generation exists; no serving route in TV1 API | Files present | None at TV4 | TV4 media adapter | CODE GAP | HIGH | Browser transport is absent, asset is not | TV4/TV5 | Narrow contained thumbnail route or approved TV1 route + TV4 proxy | None | Fixture thumbnail | correct MIME/cache; identity/path containment | E05,E06 |
| Raw original-video playback | E03 invariants/WP13 | TV1/TV3 media; TV4/TV5 transport | 873 MP4s | corpus manifest `original_video_path` | WP04 service already streams originals | Source present; active data handover not required for raw root | `/videos/{id}/stream` with Range | TV4 adapter/proxy -> player | CODE GAP | HIGH | TV4 exposes no media route although upstream code exists | TV4/TV5 | Reuse registry and Range semantics; never expose paths | None | Disable if media probe fails | HEAD/GET/206/416, read-only, 873 registry resolution | E04,E07,E18 |
| HTTP/video byte transport | E03 deployment/media | TV3 service + TV4 boundary | Same MP4s | `MediaRecord` | `_parse_byte_range`, `stream_video` | Source available | Range/HEAD contract upstream | TV4-owned transport | CODE GAP | HIGH | Missing adapter/route, not missing transport implementation | TV4 | Port/wrap minimal proven semantics with containment | None | Fixture stub, explicitly non-live | browser seeking across start/middle/end; traversal/symlink tests | E07,E20 |
| Seeking by canonical timestamp | E03 invariants 2-5 | WP01/02/09; UI TV5 | media + PTS records | PTS/time-base and `timestamp_ms` | WP04 `/resolve`; WP09 resolver | Present upstream | resolve/window/exact APIs | TV4 -> player + proof | CODE GAP | HIGH | UI/state glue absent; browser seek must not create identity | TV4/TV5 | Carry canonical timestamp separately from playback position | None | Anchor-only inspection | VFR/seek drift tests; displayed identity unchanged | E07,E15,E18 |
| Original-frame still image | E03 WP09/WP13 | WP04 service; TV4/TV5 | decoded from raw MP4 | frame resolver record | `original_frame` route | Source exists | `/videos/{id}/frames/{frame_id}.jpg` | TV4 proxy | CODE GAP | HIGH | Existing upstream route is not exposed through TV4 | TV4 | Proxy with identity headers/provenance | None | Fixture still | returned headers match requested canonical record | E07 |
| Exact previous/current/next ORIGINAL frames | E03 WP09 | WP09 TV2; TV4 | Raw MP4 + certified anchors | certification + original consecutive decode | `ExactFrameResolver`; TV4 neighbor endpoint | WP09 synced; TV4 inspected hashes match | `POST /exact-frame/neighbors` | TV4 -> WP13 inspector | PARTIAL | HIGH | Code exists, but certification samples only 4 videos/12 anchors and states VFR not live sampled | TV2/TV4 | Run full representative proof; preserve fail-closed behavior | None | Fixture frames nonselectable | boundaries/VFR/seek/back-seek/PTS/provenance suite + live sample | E15-E18,E24 |
| Repeated signed cumulative stepping | E03 WP13 UI | WP09/TV4/TV5 | Same | certified anchor + cumulative offset | `certified_step_request` path | Present | neighbor request fields | Inspector state | PARTIAL | HIGH | Backend path exists; no WP13 state/interaction proof | TV5 plus TV4 tests | Maintain original certified anchor; never promote returned neighbor | None | Nonselectable fixture | +1,+1,-1 and boundary traces equal original decode order | E18,E24 |
| Selection of newly inspected neighbor | Hard invariant | WP09/TV4/TV5 | Same | `submission_selectable` proof | TV4 revalidates certification/hash/source/time-base | Present | neighbor response proof | Inspector -> basket guard | PARTIAL | HIGH | Backend guard exists; basket/UI absent and live proof incomplete | TV5; TV2/TV4 proof | Basket accepts only live proven frame | None | Fixture always rejects | forged/fixture/stale proof rejected; valid live proof accepted | E15-E18,E24 |
| Canonical media/mapping registry | E03 WP00-02 | TV1 authority | manifest, media, frames, mappings | `(video_id,frame_id,PTS,time_base)` | Registries and validators | Corpus-scale artifacts | TV1 API/files | TV4 configured registry | READY | HIGH | Registry exists; transport/consumers still need checks | TV1 maintain; TV4 consume | Read-only, digest-locked consumption | None | Known anchors | 873 records; 106,380 mappings; random visual audit | E04-E06 |

### C. Feedback

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| WP08 reference-frame feedback | E03 WP08/WP13 | Model TV2; UI TV5 | WP03 pool/indexes | `CandidateId` + pool snapshot | Full session service and WP03 adapter | Source present | Python service contract | Must be adapted through TV4 | CODE GAP | HIGH | No TV4 endpoint/client/fixture | TV4/TV5 | Add narrow session start/refine/undo/reset/get adapter | WP03 final coverage | Original search remains usable | contract tests against actual WP08 state machine | E13,E14,E18 |
| Original query preservation | E03 WP08 | WP08 TV2 | SQLite session state | immutable session state | `start_session` stores `original_query` | Source present | `FeedbackSessions` | Via future seam | READY | HIGH | No upstream logic gap | TV4/TV5 integration | Expose without rewriting | None | Fixture copy | two refinements retain byte-identical original query | E14 |
| Reference identity | E03/invariants | WP08/TV4 | rendered WP03 pool | `CandidateId(video_id,frame_id)` | Selection restricted to rendered list | Source present | Python contract | Future seam + canonical revalidation | PARTIAL | HIGH | WP08 ID lacks run/proof fields at HTTP boundary; TV4 seam absent | TV4 | Bind pool/run provenance and revalidate before selection | WP03 final coverage | Reject unknown reference | forged/out-of-view/stale run rejected | E14 |
| Feedback history/reset behavior | E03 WP08 | WP08 TV2 | persisted events/revisions | session/revision CAS | refine/undo/reset/get; 24h TTL | Source present | Python contract | Future seam | READY | HIGH | Upstream state behavior exists | TV4/TV5 | Preserve events, snapshots and basket isolation | None | Deterministic session fixture | reset restores original; history/audit and basket retained | E14 |
| Current WP08 integration seam | E03 TV4 boundary | TV4/TV5 | Existing WP08 code | Above | None in TV4 | None | No HTTP/CLI adapter | TV4 endpoint -> WP13 | CODE GAP | HIGH | Transport and serialization only | TV4 | Adapter, schemas, error mapping, health probe | WP03 for full-live | Explicit unavailable | start/refine/undo/reset contract suite | E14,E18 |
| Advanced feedback/reranking | E03 benchmark gate | WP08 TV2 | four-model smoke pool | embedding refs/digests | Four-model ranker + stable config gate | Not proven approved for contest | Python runtime | Behind same seam | PARTIAL | HIGH | Benchmark approval/config and final coverage not established | TV2; TV5 displays status | Enable only with `StableFeedbackConfig` evidence | WP03 final | Disable advanced path, keep original results | benchmark ID + approval timestamp + first-correct comparison | E13,E14,E25 |

### D. Evidence modalities

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OCR text | E03 WP04 | TV3 | Producer/source/index contracts; current artifact absent | frame/time | OCR producer/search | Empty current run | `/ocr/search`, detections | TV4 branch -> evidence UI | HANDOVER PENDING | HIGH | Corrected artifact/index pending; capability is not nonexistent | WP04 owner | Accept handover; retain consumer/degraded code | Yes | Empty branch, visible | schema/linkage/coverage/search goldens | E08-E10 |
| OCR bbox/polygon | E03 EvidencePack | TV3/TV5 | bbox/crop fields/source | frame identity | detailed catalog/crop route | Artifact pending | detections/crop | TV4 rich evidence adapter | HANDOVER PENDING | HIGH | Data pending; TV4 currently flattens it | WP04 + TV4 | Handover then preserve geometry/model fields | Yes | Placeholder absent | overlay matches source image and normalized coordinates | E08-E10,E21 |
| ASR transcript | E03 WP04 | TV3 | producer/search contracts | video interval | ASR search/catalog | Artifact pending | `/asr/search` | TV4 branch -> UI | HANDOVER PENDING | HIGH | Corrected transcript/index pending | WP04 | Validate and mount | Yes | Empty branch | query retrieves correct video/window | E08-E10 |
| ASR timing/context | E03 EvidencePack | TV3/TV5 | start/end/context contract | PTS-time window | segments/context route | Artifact pending | `/asr/segments`, context | TV4 rich adapter | HANDOVER PENDING | HIGH | Data pending; current EvidencePack drops timing/context | WP04 + TV4 | Preserve interval and neighboring transcript | Yes | Visible unavailable | context radius and original window linkage tests | E08-E10,E21 |
| Object labels | E03 WP04 | TV3 | detector/search contract | frame/time | object search soft/hard mode | Artifact pending | `/object/search` | TV4 soft branch | HANDOVER PENDING | HIGH | Corrected detections pending | WP04 | Validate; keep soft default | Yes | No object boost | missing object never hard-excludes baseline | E08-E10,E19 |
| Object bbox/crop if supported | E03 EvidencePack | TV3/TV5 | bbox/source-keyframe fields; no required crop contract | frame identity | detections endpoint | Artifact pending | `/objects/detections` | TV4 rich adapter | HANDOVER PENDING | HIGH | Bbox handover pending; dedicated crop is optional/not promised | WP04 + TV4 | Preserve bbox; expose crop only if handed over | Yes | Labels-only/absent | bbox overlay correct; no fabricated crop | E08-E10 |
| Metadata retrieval | E03 WP04 | TV3 | producer/search contract | video/window | metadata search/catalog | Artifact pending | `/metadata/search` | TV4 branch | HANDOVER PENDING | HIGH | Corrected records/index pending | WP04 | Accept handover | Yes | Dense continues | provenance/linkage/search test | E08-E10 |
| Independent modality retrievers | E03 invariants 13-14 | WP04/TV4 | branch contracts | candidate canonicalization | Independent TV3 endpoints + TV4 clients | Artifacts pending | SearchCandidate lists | RRF | HANDOVER PENDING | HIGH | Runtime data, not architecture, is pending | WP04 | Validate each branch independently | Yes | Dense-only | each branch can fail without stopping visual | E08-E10,E19-E20 |
| Multimodal evidence/provenance | E03 EvidencePack | TV3/TV4/TV5 | detailed catalog fields | evidence refs -> records | SearchCandidate provenance exists | VQA flattens strings | Current `EvidencePack` | TV4 -> WP13 | CODE GAP | HIGH | bbox/timing/context/record refs lost in TV4 | TV4 | Extend typed contract and query-aware retrieval | WP04 for live data | Typed fixture evidence | round-trip every source/ref/geometry/timing field | E09,E18,E21 |
| preprocess/model/config/source provenance | E03 contracts | All producers; TV4/TV5 | manifests/digests exist | run IDs | Candidate carries some run/model maps | Inconsistent/flattened | JSON fields | status/evidence UI | PARTIAL | HIGH | Config/source/checksum not end-to-end; WP13 absent | TV4/TV5 | Preserve typed provenance and config lock | Handovers for final values | Fixture provenance label | no selected/exported item lacks required run/source proof | E03,E11,E15,E19,E21 |
| Selected-frame/multiframe evidence | E03 WP11 | WP09/TV4 | raw video + mapped frames | exact proof | TV1 keyframe windows; WP09 exact frames | Available upstream | APIs/CLI | VQA evidence panel | CODE GAP | HIGH | Current neighbors are selected keyframes, not rich proven adaptive frames | TV4 | Use exact service and retain proof; bound 4-16 frames | None | Fixture frames | evidence-visible original frames; empty is explicit | E06,E07,E15,E21 |

### E. Contest workflows

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| VQA evidence retrieval | E01/E03 WP11 | TV4 | branch/source APIs | candidate window | `build_evidence_pack` | Present | `/vqa/answer` | TV4 -> WP13 | INCOMPATIBLE | HIGH | Probe sends `query_text=None, question=None`; detailed evidence flattened | TV4 | Pass original description/question and fetch typed nearby evidence | WP04 live data | Manual/fixture evidence | query-aware OCR/ASR/Object/multiframe tests | E21 |
| VQA proposal/confidence | E03 WP11 | TV4 | optional VLM | evidence pack | Protocol + rule fallback | Rule fallback only | `/vqa/answer` | proposal panel | PARTIAL | HIGH | Candidate confidence is not proposal confidence; no approved VLM/verifier | TV4 | Advisory proposal/status/confidence/verifier contract | VLM operational approval | Abstain/manual | weak/unavailable engine never auto-confident | E18,E21 |
| VQA human confirm/edit | E03 WP11/WP13 | TV5 | None | candidate + evidence revision | None | None | No approval contract | UI -> basket | CODE GAP | HIGH | WP13 approval state absent | TV5 | Explicit editable approval; immutable approved text | None | Manual entry | zero unconfirmed exports; whitespace/Unicode preserved | E26,E27 |
| VQA empty-evidence/degraded semantics | E03 invariant 16 | TV4/TV5 | None | candidate retained | `manual_fallback` predicate and rule verifier | Present | `/vqa/answer` | UI | INCOMPATIBLE | Any nonempty OCR/ASR text verifies; manual flag only when unverified *and* no evidence | TV4 | Explicit empty/weak/abstain; fail confidence closed; one controlled retry | WP04/VLM for live | Manual-only | empty evidence produces no confident answer | E21 |
| VQA controlled retry | E03 WP11 | TV4 | Wider window | same candidate | None | None | None | TV4 -> UI | CODE GAP | HIGH | Approved at-most-one retry not implemented | TV4 | Add bounded retry status/audit | None | No retry, manual | exactly 0/1 retry; no corpus-wide VLM | E03,E21 |
| TRAKE alignment | E01/E03 WP12 | TV4 | event candidate lists | single video + ordered timestamps | DP + greedy | Present | `/trake/align` | timeline UI | PARTIAL | HIGH | Only one hypothesis; no WP09 fine alignment despite module description | TV4 | Preserve baseline, integrate exact fine alignment | WP03/WP04 coverage | no-alignment explicit | organizer 4-event case; interval improvement | E18,E22 |
| TRAKE event count | E01/E03 | TV4/TV5 | events | event position | pool count drives frame list | Present | list `frame_ids` | UI/basket | PARTIAL | HIGH | Response omits explicit event identities/validation state | TV4/TV5 | Return `(event_index,text,frame)` and validate N | None | reject incomplete | exactly N for N events | E18,E22 |
| TRAKE event ordering | E01/E03 | TV4/TV5 | ordered query | event index + monotonic time | Router order + DP | Present | implicit list order | UI/basket/export | PARTIAL | HIGH | Semantic association is implicit and greedy may return nonmonotonic if repair fails | TV4 | Make event slots explicit; reject any invalid chain | None | no result | semantic order and temporal exception tests | E19,E22 |
| TRAKE lock/unlock/reorder validation | E03 WP13 | TV5 | None | immutable event slots | None | None | None | WP13 state | CODE GAP | HIGH | UI state machine absent | TV5 | Locks, corrections, audit, pre-basket validation | None | Fixture | locked slots survive; numerical sorting never reorders semantics | E26,E27 |
| TRAKE diverse hypotheses | E03 WP12 | TV4 | candidate pools | chain ID | Only single DP/greedy output | Present | single `result` | UI | CODE GAP | HIGH | No up-to-100 diverse hypotheses | TV4 | Add bounded diverse chains where supported | Final coverage | Single hypothesis labeled | diversity/count/order tests | E18,E22 |
| KIS exact workflow | E03 WP10 | TV4/TV5 | KIS candidates + WP09 | certified identity | refine top 5 + neighbor endpoint | Present | KIS + exact APIs | WP13 | PARTIAL | HIGH | UI/basket absent; live proof scope incomplete | TV4/TV5 | Integrate without replacing canonical coarse anchor on failure | WP03 final | coarse anchor remains | query->inspect->exact->basket E2E | E18-E20 |
| KIS/VQA/TRAKE mode switching | E03 WP13 | TV5 | fixtures/APIs | query-scoped state | None | None | Three TV4 endpoints exist | WP13 shell | CODE GAP | HIGH | Integrated UI/state absent | TV5 | Typed mode/session isolation | None | All fixtures | switching never leaks basket/events/answer state | E18,E24,E27 |

### F. Operator workflow

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Submission basket | E03 WP13 | TV5 | None | canonical identity + query | None | None | None | UI state | CODE GAP | HIGH | No basket implementation | TV5 | Query-scoped ordered basket with readiness audit | None | Fixture | visible order equals export order | E26,E27 |
| <=100 enforcement | E01 | TV4/TV5 | None | query | API `top_k<=100`; no basket/export validator | Present partially | Pydantic request only | basket/export | CODE GAP | HIGH | 101st basket/export row is not guarded end-to-end | TV5 | Reject 101st without mutation | None | Fixture | 100 accepts, 101 rejects | E18,E23,E27 |
| Canonical identity preservation | E03 invariants | TV5 | upstream proofs | `CanonicalFrameIdentity` | Derived model only | None | contracts partial | result -> basket -> export | CODE GAP | HIGH | WP13 state and validation absent | TV5 | Immutable identity/proof object and revalidation | None | Fixture proof scoped | no proxy/keyframe/PTS/UI identity export | E15,E18,E26 |
| Keyboard shortcuts | E03 WP13 | TV5 | None | guarded commands | None | None | None | UI | CODE GAP | HIGH | No shortcut registry/focus guards/help | TV5 | Implement after workflow states | None | Fixture | shortcuts cannot bypass confirm/lock/proof | E26,E27 |
| Runtime/live/fixture/degraded status | E03 G4 | TV4/TV5 | configs/fixtures | run/config IDs | basic TV4 health/mode | Present | `/health` | status panel | PARTIAL | HIGH | Health only proves config construction; no component probes; no WP13 panel | TV4/TV5 | Component readiness/capability impact | Handovers for final | Fixture labeled | every dependency failure maps to honest impact/fallback | E18,E24 |
| Operator draft persistence/recovery | E03 deployment | TV5 | None | revision/checksum | Model only in data-model | None | None | WP13 state | CODE GAP | HIGH | No atomic state, restore, revalidation | TV5 | Persist only WP13 mutable state | None | In-memory fixture | interrupted write/restore/revalidate suite | E26,E27 |

### G. Submission

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| KIS exporter | E01 + provisional E02 | TV5 | basket | canonical IDs | TV4 exporter exists | Runtime differs | CLI CSV | WP13 exporter | INCOMPATIBLE | HIGH | Writes header and query/rank columns | TV5 | Independent headerless 2-field exporter | None | Golden fixture | exact bytes/round-trip | E01-E02,E23,E28 |
| VQA exporter | E01 + provisional E02 | TV5 | approved answer | canonical IDs | TV4 exporter exists | Runtime differs | CLI CSV | WP13 exporter | INCOMPATIBLE | HIGH | Writes header/query/rank and exports machine-normalized answers without approval state | TV5 | Headerless 3-field approved-text exporter | None | Golden fixture | commas/quotes/newlines/whitespace/Unicode round-trip | E01-E02,E21,E23 |
| TRAKE exporter | E01 + provisional E02 | TV5 | validated chain | event positions | TV4 writes JSON | Present | CLI JSON | WP13 exporter | INCOMPATIBLE | HIGH | Required per-query CSV not implemented | TV5 | Headerless video+N frames CSV | None | Golden fixture | exact N and semantic order | E01-E02,E23 |
| CSV formatting | Provisional E02 | TV5 | None | task schema | `csv.writer` but wrong shape/header | Present | CSV CLI | WP13 | INCOMPATIBLE | HIGH | UTF-8 writer exists, contract shape does not | TV5 | Standards-compliant headerless serializers/parsers | None | Goldens | UTF-8/comma/LF-or-CRLF/no header; reopen | E02,E23 |
| Answer preservation/quoting | E01 semantic; E02 mechanics | TV5 | operator approval | answer bytes | `normalize_answer.strip()` before export | Present | QA CLI | WP13 | INCOMPATIBLE | HIGH | Leading/trailing whitespace and approved bytes can be changed | TV4 pre-proposal; TV5 post-approval | Normalize only before proposal; after approval escape only | None | Goldens | byte-faithful parsed answer; <=100 provisional | E01-E02,E21,E23 |
| Filename/query naming | Provisional E02 | TV5 | input query names | suffix mapping | Generic `kis.csv/qa.csv/trake.json` | Present | CLI | WP13 | CODE GAP | HIGH | `query-N-{kis,qa,trake}.csv` mapping/validation absent | TV5 | Deterministic mapper; ambiguous suffix fails | Official 2026 guide review | Fixture | filename goldens | E02,E23 |
| ZIP/package layout | Provisional E02 | TV5 | validated CSVs | inventory/digests | None | None | None | CLI/UI | CODE GAP | HIGH | No top-level `submission/` ZIP builder/reopen validation | TV5 | Safe deterministic ZIP builder | Official 2026 guide review | Golden package | reject root CSV/traversal/missing/unexpected files | E02,E26-E27 |
| Validation/fail-closed | E03 WP13; provisional E02 | TV5 | registries + files | identity and event proof | None | None | None | CLI/UI | CODE GAP | HIGH | No basket/file/package validator | TV5 | Aggregate all detectable errors; unknown required check blocks ready | None | Invalid fixtures | complete negative matrix | E02,E26-E27 |
| CLI fallback | E03 deployment | TV5 | None | same validators | TV4 CLI exists | Exists but wrong outputs | `python -m tv4` | WP13 CLI | INCOMPATIBLE | HIGH | Retrieval CLI is not a contest-safe prepare/validate/package fallback | TV5 | Independent non-UI preparation CLI | None | Fixture | UI-down golden package | E23,E26 |
| Upload/manual boundary | E02 provisional; FR-042 | Human operator | Local ZIP | N/A | No upload automation | None | Manual Codabench | outside app | READY | HIGH | No code gap; must remain human-controlled | Human | Show artifact/report only | Official guide review | Same | automated tests make zero network uploads | E02,E26 |
| Per-query maximum predictions | E01 | TV4/TV5 | ranked/basket rows | rank | API request capped; exporters do not validate | Partial | APIs/CLI | basket/export | PARTIAL | HIGH | Retrieval cap exists; file/package enforcement absent | TV5 | Enforce at basket and validator | None | Fixture | 0/100/101 tests | E01,E18,E23 |

### H. Evaluation

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Official task R-Score | E01 §2.1 | TV5 | Formula/examples | GT intervals/events/verdict | None | None | None | evaluator | CODE GAP | HIGH | No WP13 scorer | TV5 | Pure KIS/VQA/TRAKE scorer; semantic verdict input | GT/adjudication for dataset claims | Organizer goldens | KIS 0/1, VQA conjunctive, TRAKE 0.75 | E01,E26-E27 |
| R@1/5/20/50/100 | E01 §2.2 | TV5 | Formula | rank order | None | None | None | evaluator | CODE GAP | HIGH | No implementation | TV5 | max first-k R-Score | None | Goldens | exact thresholds | E01,E26-E27 |
| Final Score | E01 §2.2 | TV5 | Formula | R@k | None | None | None | evaluator | CODE GAP | HIGH | No implementation | TV5 | arithmetic mean of five R@k | None | Golden | 0.74 example | E01,E26-E27 |
| Video Hit@K | E03 WP13 | TV5; upstream report source | Labelled retrieval reports | video ID | WP04 benchmarking has implementation | Source exists | Python report | ingestion/UI | PARTIAL | HIGH | Upstream metric exists; WP13 aggregation/provenance absent | TV5 | Reuse/ingest validated report or implement pure equivalent | labels for live | `INCOMPLETE` without labels | golden labelled ranks | E25-E27 |
| Frame Interval Hit@K | E03 WP13 | WP09 source; TV5 | Exact benchmark records | frame intervals | WP09 benchmark exists | Synced | Python report | ingestion/UI | PARTIAL | HIGH | WP13 evaluator/report integration absent | TV5 | Reuse pure formula and retain run/config | labels | `INCOMPLETE` | exact OFF/ON golden | E15,E17,E25-E27 |
| VQA metrics | E03 WP13 + E01 | TV5 | semantic verdicts | video/frame/answer | None | None | None | evaluator | CODE GAP | HIGH | No accuracy/E2E engine; semantic judging cannot be guessed | TV5 | Accept authoritative verdict/adjudicator output | GT/verdicts | `INCOMPLETE` | never substitute exact string | E01,E26-E27 |
| TRAKE alignment metrics | E03 WP13 + E01 | TV5 | GT event intervals | semantic event index | alignment algorithm only | Present upstream | None for evaluation | evaluator | CODE GAP | HIGH | No per-event/video metric report | TV5 | Pure event hit/alignment breakdown | GT | `INCOMPLETE` | wrong video zero; per-event fractions | E01,E22,E26-E27 |
| Latency p50/p95 | E03 WP13 | TV5; upstream producers | upstream samples | run/config | WP09 and WP04 benchmarks | Source present | reports | telemetry ingestion | PARTIAL | HIGH | Not unified across task paths | TV5 | Bounded telemetry and percentile report | None | Fixture timing labelled | observed-sample p50/p95 by capability | E25-E27 |
| Time-to-first-correct | E03 WP08/WP13 | WP08/TV5 | feedback samples | session/revision | WP08 records immutable first correct | Source present | Python metrics | TV4/WP13 telemetry | PARTIAL | HIGH | No seam/report/UI | TV4/TV5 | Expose only externally judged correctness | labels | fixture labelled | feedback/no-feedback cohorts | E14,E25-E27 |
| Submission error rate | E03 WP13 | TV5 | validator results | package/query | None | None | None | telemetry/report | CODE GAP | HIGH | Validator and telemetry absent | TV5 | Count attempted validations/errors by rule/version | None | Fixtures | deterministic numerator/denominator | E26-E27 |
| Preprocessing throughput/storage ingestion | E03 §8/WP13 | Upstream producers; TV5 reader | WP03/WP04/WP09 reports and run metrics | run/model/config | Partial upstream reports | Present in source/artifacts | Files/Python | read-only adapter | CODE GAP | HIGH | No WP13 report schema/reader; preprocessing must not run | TV5 | Ingest validated reports only | Approved reports | unavailable/incompatible status | provenance/schema/digest checks; zero producer invocation | E11,E25-E27 |

### I. Operations and deployment

| Capability | Requirement authority | WP/owner | Physical asset | Canonical mapping | Tracked impl | Runtime impl | API/CLI/contract | WP13 path | Status | Conf. | Exact gap | Gap owner | Required action | Handover | Degraded/fixture | Acceptance gate | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `/health` and real dependency readiness | E03 G4 | TV4/TV5 | service configs/artifacts | run/config IDs | Basic TV4 health; richer WP04 health | Present | `/health` | status panel | PARTIAL | HIGH | TV4 reports OK after construction, not WP03/WP04/WP08/WP09/VLM/media probes | TV4/TV5 | Component probes and capability impact | Final services | fixture-only label | induced failure matrix | E07-E10,E18 |
| Fixture mode | E03 invariant 21 | TV4/TV5 | canned payloads | fixture-only IDs | KIS/VQA/TRAKE/exact fixtures | Present | env `TV4_FIXTURE_MODE` | WP13 | PARTIAL | HIGH | No Feedback/rich evidence/full degradation/submission/eval UI fixtures | TV4/TV5 | Complete deterministic contract-valid family | None | Primary pre-backend path | repeatable bytes/order and explicit FIXTURE label | E18,E24,E27 |
| Degraded mode | E03 invariants | All; UI TV5 | partial branches | preserved coarse identity | Some empty-branch/failure handling | Present | mixed | WP13 | PARTIAL | HIGH | Status is not typed/scoped; unsafe VQA and absent UI | TV4/TV5 | Capability-specific degradation and safe fallback | Handovers improve | dense/manual/anchor fallback | zero fabricated frames/answers/readiness | E18-E21,E24 |
| Config lock | E03 deployment | TV5 | manifests/digests | run/config | None | None | None | deployment | CODE GAP | HIGH | No frozen compatibility manifest | TV5 | Lock roots, digests, model/schema/config; exclude secrets | Final handovers | current-partial lock | change invalidates readiness | E26-E27 |
| Docker Compose | E03 WP13 | TV5 + TV1 support | upstream services exist | mount/config IDs | No WP13 compose | None | None | deployment | CODE GAP | HIGH | TV1 compose does not satisfy WP13 orchestration | TV5/TV1 | WP13 compose with external services/read-only mounts/probes | Final roots | fixture/current profiles | fresh start without preprocessing | E26-E27 |
| Backup/restore | E03 G4 | TV5 | future mutable state | checksums/config lock | None | None | None | ops | CODE GAP | HIGH | No WP13 state backup/restore | TV5 | Atomic manifest/checksum backup; exclude upstream/secrets | None | fixture rehearsal | interrupted write and restore/revalidate | E26-E27 |
| RUN_BOOK | E03 deployment | TV5 + TV1 | docs planned | service/run IDs | Quickstart is future plan, not runbook | None | None | operator | CODE GAP | HIGH | No tested `RUN_BOOK.md` | TV5/TV1 | Three modes, order, health, exact, fallback, recovery, no preprocessing | Final values | fixture/current sections now | non-owner completes dry run | E26-E27 |
| Target TV4 machine handoff | E03 G4 | TV5 + TV1 | Target environment | config/artifact freeze | None | None | None | release | CODE GAP | HIGH | No target evidence/non-owner exercise | Team | Fresh start, live flows, package, restore | Handovers required final | fixture/current rehearsal | signed non-owner acceptance | E03,E26-E27 |
| Tracked/runtime synchronization policy | Workspace rules | Module owners | tracked/runtime trees | hashes/version | WP09 explicit report; TV4 copies mostly match | WP09 34/34; TV4 submission drift | Hash reports | release process | PARTIAL | HIGH | WP09 synchronized; TV4 lacks equivalent complete policy/evidence and submission differs | TV4/TV5 | Tracked-first reviewed, per-file hash report; never hotfix runtime | None | Source-only dev | zero missing/mismatch for approved release set | E17,E28 |
| Final smoke/E2E/mock acceptance | E03 G4 | Team; TV5 lead | all above | frozen identities | Tests/plans only | Not executed | future suites | release gate | CODE GAP | HIGH | No WP13 app, full live E2E, three P0-clean mocks or recovery evidence | Team | Execute only after slices and handovers | Yes | Current partial suite first | all task journeys, 3 mocks, fresh target, backup/restore | E03,E26-E27 |

## Status totals

Machine-counted from the 83 matrix rows above:

| Status | Rows |
|---|---:|
| READY | 6 |
| PARTIAL | 24 |
| HANDOVER PENDING | 9 |
| CODE GAP | 37 |
| INCOMPATIBLE | 7 |
| ACTUALLY MISSING | 0 |

## A. System dependency graph

```text
AIC 2026 official semantics ----+                 +--> WP13 KIS/VQA/TRAKE UI
Final Pipeline contracts -------+--> TV1/WP02 ----+--> basket/export/validator
AIC 2025 provisional mechanics -+    identity     +--> official/internal evaluation
                                     registry     +--> telemetry/status/recovery
Raw MP4 (873) -> run_v1_batch1 -> keyframes/thumbnails/mappings
                         |          |             |
                         |          +-> WP03 visual/FAISS -- handover pending for full coverage
                         +------------> WP04 evidence ------ handover pending for corrected artifacts
                                      -> WP04 media Range/original-frame source already exists
WP03 pool -> WP08 feedback state/ranker --------------------+
Raw video + anchors/certification -> WP09 exact neighbors --+--> TV4 boundary
WP03 + WP04 -> WP07 router/RRF -> WP10/11/12 ---------------+
                                                              |
                                                              +--> WP13 adapter/state/UI
                                                                   -> human-reviewed package
                                                                   -> metrics/mocks
                                                                   -> Compose/config/backup/runbook
```

WP13 must not bypass TV4 with arbitrary direct browser calls. Existing WP04 media/evidence routes are reusable implementation assets from which TV4 should expose the smallest safe browser contract.

## B. P0/P1 gap register

| Severity | Gap | Why it matters | Owner | Blocks now? | Blocks final live? | Smallest safe fix |
|---|---|---|---|---|---|---|
| P0 | Certified exact-neighbor proof remains only partially accepted | Wrong frame identity invalidates all tasks | TV2/TV4 | Blocks neighbor selection; coarse canonical search can proceed | Yes | Finish representative/VFR/seek/provenance tests around existing E4-1 path; keep unproved frames nonselectable |
| P0 | Safe TV4 media/image transport absent | Browser cannot inspect source-of-truth through approved boundary | TV4/TV5 | Blocks real inspection UI | Yes | Wrap existing WP04 Range/frame behavior with registry containment and tests |
| P0 | WP13 app/state/UI absent | No operator product | TV5 | Yes | Yes | Build fixture-first shell and one vertical KIS inspection slice |
| P0 | TV4 VQA evidence/empty-evidence behavior incompatible | Can present ungrounded/incorrect confidence | TV4 | Blocks safe VQA implementation | Yes | Query-aware typed EvidencePack; explicit abstain/manual; verifier boundary |
| P0 | Feedback transport absent | Final Pipeline workflow cannot reach UI | TV4/TV5 | Blocks Feedback slice only | Yes for complete product | Thin adapter over real WP08 contract; no new ranker behavior |
| P0 | Submission exporters/validator/package incompatible or absent | Malformed output can consume attempts | TV5 | Blocks contest output | Yes | Independent headerless exporters + fail-closed validator + ZIP + CLI goldens |
| P0 | Basket/approval/TRAKE slot guards absent | Unsafe state can enter export | TV5 | Blocks workflows | Yes | Immutable query-scoped state and pre-basket guards |
| P0 | Official metric simulator absent | Cannot verify scoring | TV5 | Does not block early UI | Yes | Pure formula goldens before UI reporting |
| P0 | Real readiness, config lock, recovery/runbook absent | False green status and fragile handoff | TV4/TV5/TV1 | Does not block fixture coding | Yes | Component probes, lock manifest, backup, tested runbook |
| P0 | Corrected WP03 handover pending | Current search covers only 3/873 videos | WP03 owner | No for fixture/current slice | Yes | Read-only validate/freeze and rerun affected paths |
| P0 | Corrected WP04 handover pending | Final OCR/ASR/Object/Metadata unavailable | WP04 owner | No for dense/fixture/degraded slices | Yes | Read-only branch acceptance and rerun affected paths |
| P1 | Router/provenance, diverse TRAKE hypotheses, advanced Feedback incomplete | Reduces recall/operator efficiency | TV4/TV2/TV5 | No | Only if promoted to release requirement | Small bounded improvements after P0 baselines and benchmarks |
| P1 | TV4 tracked/runtime submission drift | Reproducibility ambiguity | TV4 | No (both incompatible) | Yes before freeze | Include TV4 in tracked-first hash report after reviewed fixes |

## C. Handover register

### WP03

- Exists now: four model manifests, embeddings, maps and FAISS indexes for 892 selected frames across 3 of 873 videos; search/RRF/feedback-pool code and TV4 subprocess client.
- Pending: corrected corpus-complete visual/vector handover with compatible run/model/config/index/map provenance.
- WP13 may build now: readiness validator, typed client, current-smoke KIS/Feedback, grid, evidence/provenance display, basket/export/metrics/fixtures/degraded/ops.
- Rerun after handover: schema/digest/index-map/vector/coverage validation; KIS, Feedback, routing/RRF, VQA/TRAKE retrieval dependencies, latency/E2E/mocks.
- WP13 must not rebuild: embeddings, indexes, keyframes or mappings.
- Final gate: expected coverage derived from authoritative registries; every index count equals map/vector count; all candidates resolve to `run_v1_batch1` canonical identity; frozen digests/config; live task suites pass without redesign.

### WP04

- Exists now: producer source, rich contracts, independent search endpoints, evidence catalog/crop/context endpoints, validation code, and Range/original-frame media routes. Current modality run artifacts are empty/unavailable.
- Pending: repaired/rerun OCR, ASR, Object and Metadata records/indexes/evidence plus provenance.
- WP13 may build now: typed contracts/adapters, visible missing/degraded state, evidence fixtures/renderers, VQA manual flow, health/readiness tests, dense fallback.
- Rerun after handover: per-branch schema/coverage/canonical/timing/provenance/index checks; OCR/ASR/Object/Metadata retrieval; RRF; evidence UI; VQA; TRAKE; E2E/mocks.
- WP13 must not repair producer code or run preprocessing.
- Final gate: each required branch independently READY; all records link to authoritative video/frame/time; evidence fields render correctly; branch failure still leaves dense path usable.

## D. Submission design contract

Authoritative AIC 2026 semantics:

- KIS prediction is `<video_id>,<frame_id>` and is correct only for the correct video and an original frame inside `[s,e]`.
- VQA prediction is `<video_id>,<frame_id>,<answer>` and additionally requires semantic answer agreement. Vietnamese or English is allowed. Exact-string equality from the 2025 page must not replace 2026 semantic judging.
- TRAKE prediction is `<video_id>,<frame_id_1>,...,<frame_id_N>`; wrong video gives zero, otherwise R-Score is the fraction of event-position frames inside their corresponding intervals. Event count/order is semantic.
- At most 100 predictions/query. R@k is the maximum R-Score in the first k rows for k={1,5,20,50,100}; Final Score is their mean.

Provisionally inherited from AIC 2025 until a 2026 submission guide appears:

- one headerless UTF-8 comma-delimited CSV per query; `-kis.txt -> -kis.csv`, `-qa.txt -> -qa.csv`, `-trake.txt -> -trake.csv`;
- video name without `.mp4`, integer frame IDs, ordinary RFC-style CSV escaping, LF or CRLF;
- Q&A maximum 100 characters; exactly N TRAKE frames for N events;
- ZIP contains a top-level `submission/` directory with all expected CSVs;
- manual Codabench account/upload; provisional notes say at most three attempts/package, malformed attempts count, and the last submission is ranked.

Conflicts/uncertainties:

- The 2025 guide contains exact-string wording in its operational page, while AIC 2026 explicitly requires semantic match. 2026 wins for scoring; exporter nevertheless preserves the exact approved text.
- No official 2026 packaging/attempt/100-character guide was found in the supplied 2026 PDF. These mechanics must be versioned as provisional and re-reviewed before every ready package after new organizer guidance.
- The 2025 examples visually include spaces after delimiters in prose but the canonical examples also use compact CSV. Use a standards-compliant CSV writer; whitespace inside the approved answer is data and must not be trimmed.

Required WP13 behavior: take only validated ordered basket state; write exact task-shaped headerless rows; preserve approved VQA text except CSV escaping; validate canonical identity, <=100, filename, schema, event count/order and provisional answer length; create the `submission/` tree; reopen and validate the ZIP; emit digests and a full error report; fail closed. UI and CLI preparation are required. Automated upload is forbidden. The final click/upload, account choice, attempt budgeting and organizer-site confirmation remain human/manual.

## E. Spec/plan/task/contract drift analysis

| Artifact/issue | Label | Finding |
|---|---|---|
| Complete product scope and no-preprocessing boundary | NO CHANGE | `spec.md` correctly retains full Final Pipeline scope and forbids WP13 preprocessing. |
| WP03 as external final-live handover | NO CHANGE | Correctly separated from current implementation work. |
| WP04 status vocabulary | SPEC CHANGE NEEDED | `spec.md`/readiness model calls current branch artifacts `MISSING`; this reconciliation must distinguish known external delivery as `HANDOVER PENDING` from genuine absence. Do not shrink any requirement. |
| Exact-frame current-state claim | PLAN/TASK CHANGE NEEDED | `plan.md`/`research.md` still say protocol-only/raw-PTS fallback. Staged tracked code now contains certified `ExactFrameResolver`, TV4 safe replacement checks and `/exact-frame/neighbors`; WP09 is runtime-synchronized. Remaining work is acceptance/proof and UI integration, not starting from the old defect. |
| T005-T012/T021 checkboxes and prerequisites | PLAN/TASK CHANGE NEEDED | Tasks are all unchecked although a substantial E4-1 slice and WP09 runtime sync already exist. Re-baseline with evidence; do not redo or resync WP09. TV4 runtime hashes also match the inspected exact/API files. |
| Media work described as if no transport exists | PLAN/TASK CHANGE NEEDED | TV4 lacks transport, but WP04 already implements Range streaming, original-frame JPEG and timestamp resolve. T013/T014 should explicitly reuse/adapter-test those semantics rather than design from zero. |
| WP08 boundary | NO CHANGE | Contract correctly treats advanced model as benchmark-gated and workflow as required. |
| WP04 boundary says current artifacts `MISSING` | CONTRACT CHANGE NEEDED | `wp13-boundaries.md` should later use the approved handover-aware status and distinguish data handover from TV4 rich-evidence CODE GAP. |
| Exact-frame boundary target | NO CHANGE | Its fail-closed/selectable-proof requirements remain correct and should not be weakened because code now exists. |
| Submission target | NO CHANGE | Independent WP13 exporter is justified by direct incompatibility in TV4. |
| API fallback wording | CONTRACT CHANGE NEEDED | Clarify that the existing TV4 retrieval CLI/exporter is not an approved submission fallback; WP13 CLI is mandatory and any preparation API remains conditional. |
| Runtime synchronization task | PLAN/TASK CHANGE NEEDED | T021 must record the newer WP09 34/34 synchronization fact and avoid repeating it; future work should scope only reviewed TV4/WP13 release files. |
| `tasks.md` overall sequence | PLAN/TASK CHANGE NEEDED | Reorder first action to reconcile boundary goldens against the new E4-1 state, then reuse existing media service semantics, before further implementation. |

No implementation gap above requires rewriting the product requirement. The required spec changes are terminology/current-state corrections, not scope reduction.

## F. Recommended implementation sequence

### CAN IMPLEMENT NOW

1. Boundary-golden vertical slice: characterize current staged/runtime TV4 KIS, exact-neighbor, WP03 CLI, WP04 media/evidence, WP08 and submission schemas; update future tasks only after human review.
2. Finish existing exact/media P0: tests -> remaining WP09/TV4 proof gaps -> reuse Range/original-frame transport -> contract -> fixture/live adapter -> automated proof -> manual seek/step verification.
3. WP13 foundation: tests -> typed clients/state/status -> fixture shell -> KIS grid/player/inspection -> basket guard -> manual UI check.
4. Feedback/VQA/TRAKE slices: contract tests -> minimal TV4 adapter/repair -> immutable frontend state -> fixture/live-current integration -> E2E/manual verification. Keep WP04 unavailable explicit and VQA manual-safe.
5. Contest output slice: goldens -> basket guards -> independent KIS/VQA/TRAKE serializers -> validator -> `submission/` ZIP -> CLI -> reopen/manual inspection.
6. Evaluation/operations slice: organizer metric goldens -> report ingestion/telemetry -> component health -> Compose/config lock -> backup/restore -> tested runbook.

### WAIT FOR HANDOVER

1. WP03: read-only validate corrected corpus coverage/digests/index-map compatibility and freeze it.
2. WP04: independently validate corrected OCR/ASR/Object/Metadata artifacts/indexes/evidence and freeze them.

No application redesign or upstream preprocessing is allowed at this stage.

### FINAL LIVE ACCEPTANCE

Rerun all modality/RRF/KIS/Feedback/VQA/TRAKE/exact/media/submission/evaluation/telemetry tests; perform full operator E2E and keyboard/manual checks; measure latency/time-first-correct/error; complete three consecutive P0-clean mocks; perform target-machine fresh start, config/artifact freeze, backup/restore, CLI package fallback, cross-review and non-owner handoff.

## G. Next single action

**Write and execute the E4-1 boundary-golden test prompt that characterizes the current tracked/runtime TV4 `POST /exact-frame/neighbors` plus the existing WP04 Range/original-frame media semantics, without modifying contracts yet.** The prompt must assert certified-anchor/cumulative-step behavior, fixture/non-live nonselectability, forged/stale proof rejection, registry containment, HEAD/206/416 behavior, and canonical identity headers. This is the smallest action that prevents planning from reverting to the obsolete “no exact/media capability exists” assumption and establishes the safe base for the first WP13 KIS inspection slice.

## Mutation declaration

- Git mutation: NONE
- Source/runtime mutation: NONE
- Preprocessing/artifact mutation: NONE
- Runtime sync: NONE
- Only new file: `D:\aic226\tv5\specs\001-contest-ready-wp13\WP13_INTEGRATION_MATRIX.md`
