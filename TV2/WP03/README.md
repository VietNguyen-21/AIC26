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

## BEiT-3 Windows setup for Viet (RTX 5070 Ti 12 GB)

Run these commands from the `WP03` directory. Here, `--runtime-root .` means
that `.venvs/`, `third_party/`, `model-cache/`, and `model-locks/` are local to
this checkout. They are gitignored and must not be committed.

1. Activate the dedicated BEiT-3 environment and install WP03 inference
   dependencies. Install a CUDA-capable Torch/Torchvision build suitable for
   the RTX 5070 Ti in this environment first. Do **not** install
   `third_party/unilm/beit3/requirements.txt`: it is an old training/evaluation
   dependency set that installs `deepspeed==0.4.0`, which WP03 inference does
   not use and which fails to build with modern Windows Python/Torch.

   ```powershell
   .\.venvs\beit3\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -e .
   python -m pip install -r envs\beit3.txt
   ```

2. Clone UniLM only when it is absent. If it already exists, it must be clean
   before checkout; do not reset or delete another member's edits automatically.

   ```powershell
   if (-not (Test-Path .\third_party\unilm\.git)) {
     git clone --depth 1 https://github.com/microsoft/unilm.git third_party\unilm
   }
   git -C third_party\unilm status --short
   # Continue only when the command above prints nothing.
   git -C third_party\unilm fetch --depth 1 origin 833df7e7832e5064a281131ee64a481afa8e5b95
   git -C third_party\unilm checkout --detach 833df7e7832e5064a281131ee64a481afa8e5b95
   git -C third_party\unilm rev-parse HEAD
   ```

   The last command must print
   `833df7e7832e5064a281131ee64a481afa8e5b95`. A line such as
   `M beit3/utils.py` means the checkout has a local modification; preserve it
   and resolve its owner before continuing.

3. Confirm CUDA and the exact UniLM retrieval model registration before
   downloading/building the corpus. This is a fast failure gate for the
   dedicated environment.

   ```powershell
   python -c "import torch, timm, torchscale, sentencepiece, transformers; assert torch.cuda.is_available(); print('torch=', torch.__version__, 'cuda=', torch.version.cuda, 'gpu=', torch.cuda.get_device_name(0))"
   $env:PYTHONPATH = "$(Resolve-Path .\third_party\unilm\beit3)"
   python -c "import modeling_finetune; from timm.models import is_model; assert is_model('beit3_base_patch16_384_retrieval'); print('BEiT-3 retrieval import OK')"
   Remove-Item Env:PYTHONPATH
   ```

4. Download the official checkpoint and SentencePiece model, verify the
   checkpoint size, then create its local lock. Do not put either downloaded
   file in Git.

   ```powershell
   New-Item -ItemType Directory -Force .\model-cache\beit3, .\model-locks | Out-Null
   Invoke-WebRequest -Uri https://github.com/addf400/files/releases/download/beit3/beit3_base_patch16_384_coco_retrieval.pth -OutFile .\model-cache\beit3\beit3_base_patch16_384_coco_retrieval.pth
   Invoke-WebRequest -Uri https://github.com/addf400/files/releases/download/beit3/beit3.spm -OutFile .\model-cache\beit3\beit3.spm
   if ((Get-Item .\model-cache\beit3\beit3_base_patch16_384_coco_retrieval.pth).Length -ne 445025515) { throw 'BEiT-3 checkpoint size is incorrect; delete it and download again.' }
   python -m wp03 lock-model --model beit3 --checkpoint .\model-cache\beit3\beit3_base_patch16_384_coco_retrieval.pth --lock-path .\model-locks\beit3.json
   ```

5. The initial smoke configuration uses BEiT-3 batch size `4` for the 12 GB
   RTX 5070 Ti. WP03 retries once at a smaller batch on CUDA OOM and falls back
   from `bfloat16` to `float16` when the runtime reports unsupported BF16.

6. After receiving an updated WP03 checkout, refresh the dependencies in each
   isolated worker environment. In particular, BGE-VL and MetaCLIP2 need
   `sympy` for their Transformers/Torch imports; installing it only in the
   coordinator environment does not fix their subprocesses.

   ```powershell
   .\.venvs\bge_vl\Scripts\python.exe -m pip install -r envs\bge_vl.txt
   .\.venvs\metaclip2\Scripts\python.exe -m pip install -r envs\metaclip2.txt
   .\.venvs\perception\Scripts\python.exe -m pip install -r envs\perception.txt
   ```

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
