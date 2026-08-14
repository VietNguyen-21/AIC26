# WP03 — Visual Ensemble Retrieval

WP03 reads canonical TV1 `frames.parquet` (or compatible `frames.jsonl`) and its keyframes, builds one exact FAISS
`IndexFlatIP` per model, then returns one RRF-fused list of pipeline candidates
with `source: "visual"`. It never changes TV1 mapping data.

## Contract

- Input paths are relative to `--data-root`; traversal, drive, UNC and symlink
  escapes are rejected.
- Canonical map artifact is Parquet. A vector maps exactly to
  `video_id`, `frame_id`, `timestamp_ms` and `keyframe_path`.
- Vectors persisted to disk are `float32`, finite and L2-normalized.
- RRF uses `k=60`. Individual model scores stay only in audit metadata.
- A model with a different semantic/compatibility fingerprint is excluded from
  a query; a runtime dtype change alone is audit information.
- Completed model artifacts are immutable unless a build explicitly passes
  `--resume`; resume reuses only checksum- and digest-valid shards.
- A partial build writes `reports/build-summary.json` with `degraded: true` and
  preserves artifacts for its successful models.

## Pinned models

| Key | Model | Revision |
| --- | --- | --- |
| `beit3` | BEiT-3 Base COCO Retrieval | `833df7e7832e5064a281131ee64a481afa8e5b95` |
| `bge_vl` | `BAAI/BGE-VL-large` | `40fb48217f521df22a2a5bf15edd52ed1146ef05` |
| `metaclip2` | `facebook/metaclip-2-worldwide-huge-quickgelu` | `c139061af7b10fdb2e754b60d2b1182a3d5526c2` |
| `perception` | `facebook/PE-Core-B16-224` | `a16450b46fef32363459920c2685a1b4ef13dcd9` |

Each GPU worker has an isolated environment configured by
`configs/runtime.windows.yaml` or `configs/runtime.linux.yaml`. Install only
the corresponding `envs/<model>.txt` into that environment; do not install all
four stacks into the code-writing environment.

Every worker environment must also install this WP03 package from the same
checkout (`pip install -e <path-to-WP03>`) so `python -m wp03.workers.<model>`
resolves the current worker entry point.

BEiT-3 also requires a verified release checkpoint. Before it can be loaded,
run `lock-model` against the team-verified
`beit3_base_patch16_384_coco_retrieval.pth`; its expected size is 445,025,515
bytes. The lock records the actual SHA-256, rather than a guessed digest.

The BEiT-3 worker uses the pinned UniLM checkout at
`<runtime-root>/third_party/unilm/beit3`, the locked checkpoint at
`<runtime-root>/model-cache/beit3/beit3_base_patch16_384_coco_retrieval.pth`,
and `beit3.spm` alongside it. `configs/runtime.*.yaml` passes these paths as
worker-only environment variables. Clone UniLM, check out the exact revision,
then download the official checkpoint and [SentencePiece model](https://github.com/addf400/files/releases/download/beit3/beit3.spm)
before running `lock-model`; WP03 never accepts an unlocked checkpoint.

## CPU checks for Tấn

```powershell
cd WP03
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m compileall -q src
```

No model weights or GPU are required by the CPU suite.

## GPU smoke handoff for Việt

1. Copy/commit this `WP03` directory to the team repository; do not commit
   embeddings, FAISS indexes, checkpoints, virtual environments or model cache.
2. Create four isolated GPU environments under the selected `--runtime-root`
   following `envs/` and `configs/runtime.windows.yaml`.
3. Obtain the BEiT-3 checkpoint from the official release, then run:

   ```powershell
   python -m wp03 lock-model --model beit3 --checkpoint <runtime-root>/model-cache/beit3/beit3_base_patch16_384_coco_retrieval.pth `
     --lock-path <runtime-root>/model-locks/beit3.json
   ```

4. Validate TV1 input:

   ```powershell
   python -m wp03 validate --data-root <tv1-data-root> --frames frames.parquet
   ```

5. Run the smoke corpus, limited to `L21_V001`, `L21_V002`, `L21_V003` by
   `configs/smoke.yaml`. Start at batch size 4/4/1/4 and run models
   sequentially on the 12 GB RTX 5070 Ti. Every build command includes a
   reproducible code identity:

   ```powershell
   python -m wp03 build --data-root <tv1-data-root> --frames frames.parquet `
     --run-id <new-run-id> --config configs/smoke.yaml `
     --runtime-root <runtime-root> --runtime-profile configs/runtime.windows.yaml `
     --content-validation strict --code-version <team-commit-or-tag> `
     --artifact-root artifacts/<new-run-id>
   ```
6. Run at least three Vietnamese/English representative queries. A merge pass
   requires four complete manifests, valid index/map digests, and all three
   responses to list all four models in `models_used`. `degraded: true` is a
   diagnostic outcome, not a merge pass.

Return to Tấn: `build-summary.json`, four manifests, three JSON responses,
peak VRAM, elapsed time, and any normalized worker error. Do not return model
weights or generated embeddings over Git.

## Important current adapter boundary

The CPU pipeline and worker protocol are verified. The BGE-VL, MetaCLIP2 and
Perception workers load their documented backend lazily inside their dedicated
environment. The BEiT-3 worker deliberately fails closed until its exact
official retrieval API is validated against the pinned UniLM checkout and its
checkpoint lock is present. This is intentional: it prevents a plausible but
wrong image/text embedding implementation from contaminating an index. Complete
that one adapter check before declaring a four-model GPU smoke pass.
