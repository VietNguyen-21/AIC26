# AIC 2026 — Hướng dẫn chạy End-to-End (TV1 → TV2 → TV3 → TV4)

Bản tổng hợp mới nhất (đã thêm API HTTP của TV4 cho TV5 gọi vào). Cấu trúc
thư mục giả định:

```
D:\aic226\
  tv1\        <- code + data của Thành viên 1
  tv2\        <- code của Thành viên 2 (WP03/WP08/WP09)
  tv1tv3\     <- code của Thành viên 3 (TV1_TV3_WP04)
  tv4\        <- code của bạn (Thành viên 4)
```

Mọi lệnh Python dùng `python -m pytest`/`python -m <module>` thay vì gọi lệnh
trực tiếp, để tránh `ModuleNotFoundError`.

---

## Bước 0 — Chuẩn bị chung

- Python 3.11+ (khuyến nghị 3.12).
- FFmpeg trong PATH (`ffmpeg -version` chạy được).
- Git trong PATH (cần cho `perception` và `beit3` của TV2).
- GPU RTX 5070 Ti (Blackwell) → **luôn cài torch qua** `--index-url https://download.pytorch.org/whl/cu128`.
- Dữ liệu video vòng sơ tuyển đã tải theo link trong PDF luật thi, đặt vào `tv1\zip_video\`.

---

## Bước 1 — Thành viên 1 (`tv1\`): dựng dữ liệu gốc

```powershell
cd D:\aic226\tv1
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 2 file test cũ (test_wp00.py, test_wp06.py) gọi API lỗi thời, không khớp
# implementation hiện tại -> bỏ qua, không ảnh hưởng pipeline thật:
python -m pytest tests -q --ignore=tests\test_wp00.py --ignore=tests\test_wp06.py

python wp00_data_intake.py --archives_dir zip_video --raw_dir data\raw --run_dir data\runs\run_v1_batch1
python wp01_media_probe.py --raw_dir data\raw --run_dir data\runs\run_v1_batch1 --preprocess_run_id run_v1_batch1
python wp02_shot_keyframe.py --raw_dir data\raw --run_dir data\runs\run_v1_batch1 --preprocess_run_id run_v1_batch1
python wp05_temporal_adj.py --run_dir data\runs\run_v1_batch1

# GIỮ CỬA SỔ NÀY CHẠY
python wp06_api_server.py --run_dir data\runs\run_v1_batch1 --port 8000
```

Kiểm tra (cửa sổ khác): `Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health` phải trả `200`.

---

## Bước 2 — Thành viên 2 (`tv2\WP03`): visual retrieval

### 2.1. Venv `coordinator` — chạy CLI chính, không cần torch

```powershell
cd D:\aic226\tv2\WP03
python -m venv .venvs\coordinator
.\.venvs\coordinator\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pytest tests -q
deactivate
```

### 2.2. Venv cho từng model — cài deps trước, torch cu128 ép ghi đè **sau cùng**

`bge_vl`:
```powershell
python -m venv .venvs\bge_vl
.\.venvs\bge_vl\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -r envs\bge_vl.txt
python -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
deactivate
```

`metaclip2`:
```powershell
python -m venv .venvs\metaclip2
.\.venvs\metaclip2\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -r envs\metaclip2.txt
python -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
deactivate
```

`perception` (cần Git):
```powershell
python -m venv .venvs\perception
.\.venvs\perception\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python -m pip install -r envs\perception.txt
python -m pip install --force-reinstall --no-deps torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
deactivate
```

`beit3` — **đang khoá có chủ đích, chỉ setup khi TV2 xác nhận mở khoá**:
```powershell
python -m venv .venvs\beit3
.\.venvs\beit3\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
python -m pip install -e .
python -m pip install -r envs\beit3.txt

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



       ```powershell
   python -c "import torch, timm, torchscale, sentencepiece, transformers; assert torch.cuda.is_available(); print('torch=', torch.__version__, 'cuda=', torch.version.cuda, 'gpu=', torch.cuda.get_device_name(0))"




   $path = ".\third_party\unilm\beit3\utils.py"
   (beit3) PS D:\aic226\tv2_1\WP03> (Get-Content -Raw $path).Replace("from torch._six import inf", "from math import inf") | Set-Content -NoNewline $path
   (beit3) PS D:\aic226\tv2_1\WP03> Select-String -Path .\third_party\unilm\beit3\utils.py -Pattern "import inf"
   

    python -m pip install torchmetrics
    # Bỏ qua deepspeed (chỉ dùng cho training, không nằm trên đường dẫn inference).
    python -m pip install torchmetrics==0.7.3 tensorboardX


   $env:PYTHONPATH = "$(Resolve-Path .\third_party\unilm\beit3)"
   python -c "import modeling_finetune; from timm.models import is_model; assert is_model('beit3_base_patch16_384_retrieval'); print('BEiT-3 retrieval import OK')"
   Remove-Item Env:PYTHONPATH
   ```



  ```powershell
   New-Item -ItemType Directory -Force .\model-cache\beit3, .\model-locks | Out-Null
   Invoke-WebRequest -Uri https://github.com/addf400/files/releases/download/beit3/beit3_base_patch16_384_coco_retrieval.pth -OutFile .\model-cache\beit3\beit3_base_patch16_384_coco_retrieval.pth
   Invoke-WebRequest -Uri https://github.com/addf400/files/releases/download/beit3/beit3.spm -OutFile .\model-cache\beit3\beit3.spm
   if ((Get-Item .\model-cache\beit3\beit3_base_patch16_384_coco_retrieval.pth).Length -ne 445025515) { throw 'BEiT-3 checkpoint size is incorrect; delete it and download again.' }
   python -m wp03 lock-model --model beit3 --checkpoint .\model-cache\beit3\beit3_base_patch16_384_coco_retrieval.pth --lock-path .\model-locks\beit3.json
   ```



# utils.py dùng `from torch._six import inf` — API đã bị xoá khỏi torch hiện đại. Vá:
(Get-Content third_party\unilm\beit3\utils.py) -replace `
  'from torch\._six import inf', 'inf = float("inf")' | `
  Set-Content third_party\unilm\beit3\utils.py

$env:PYTHONPATH = "third_party\unilm\beit3"
python -c "import utils; import modeling_finetune; print('beit3 import chain OK')"
Remove-Item Env:\PYTHONPATH
deactivate
```
Còn cần checkpoint chính thức (`model-cache\beit3\...`) — **xác nhận với TV2 trước khi tải**.

### 2.3. Vá bug thiếu entrypoint trong 4 file worker

```powershell
$files = @(
  "src\wp03\workers\beit3.py",
  "src\wp03\workers\bge_vl.py",
  "src\wp03\workers\metaclip2.py",
  "src\wp03\workers\perception.py"
)
foreach ($f in $files) {
    Add-Content -Path $f -Value "`n`nif __name__ == `"__main__`":`n    raise SystemExit(main())`n"
}
```

### 2.4. Vá bug `perception.py`

Mở `src\wp03\workers\perception.py`, tìm:
```python
self._model = pe.CLIP.from_config(
    MODEL_ID, pretrained=True, checkpoint_path=checkpoint_path
).to(device="cuda", dtype=self._torch_dtype()).eval()
```
sửa thành:
```python
self._model = pe.CLIP.from_config(
    "PE-Core-B16-224", pretrained=True, checkpoint_path=checkpoint_path
).to(device="cuda", dtype=self._torch_dtype()).eval()
```

Sau khi sửa file `.py` bất kỳ trong `src\wp03\`, luôn xoá `__pycache__` trước khi chạy lại:
```powershell
Get-ChildItem -Recurse -Directory -Filter "__pycache__" src | Remove-Item -Recurse -Force
```

### 2.5. Build index

```powershell
.\.venvs\coordinator\Scripts\python.exe -m wp03 validate --data-root ..\..\tv1\data\runs\run_v1_batch1 --frames frames.parquet

.\.venvs\coordinator\Scripts\python.exe -m wp03 build --data-root ..\..\tv1\data\runs\run_v1_batch1 --frames frames.parquet `
  --run-id smoke-run-1 --config configs\smoke.yaml `
  --runtime-root . --runtime-profile configs\runtime.windows.yaml `
  --content-validation strict --code-version dev-local `
  --artifact-root artifacts\smoke-run-1
```

Kỳ vọng: `bge_vl`/`metaclip2`/`perception` → `"status": "complete"`; `beit3` →
`"failed"` (chấp nhận, do khoá). Nếu build lại, thêm `--resume` để không phải
build lại từ đầu các model đã xong.

### 2.6. Search thử (cần `--runtime-root`/`--runtime-profile`)

```powershell
.\.venvs\coordinator\Scripts\python.exe -m wp03 search --artifact-root artifacts\smoke-run-1 `
  --query "một diễn giả mặc áo đỏ phát biểu ngoài trời" --top-k 20 `
  --runtime-root . --runtime-profile configs\runtime.windows.yaml
```

WP08/WP09 — tuỳ chọn, để sau (TV4 mặc định tắt WP09 refine).

---

## Bước 3 — Thành viên 3 (`tv1tv3\TV1_TV3_WP04`): OCR/ASR/Object/metadata API

> Bỏ qua bước `aic preprocess` theo yêu cầu — server dưới đây khởi động ở
> chế độ rỗng, TV4 vẫn chạy bình thường vì tự xử lý các nhánh OCR/ASR/Object
> trả rỗng/503.

```powershell
cd D:\aic226\tv1tv3\TV1_TV3_WP04
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

aic doctor --config configs\default.yaml
python -m pytest -q

New-Item -ItemType Directory -Force -Path "data\runs\tv1-tv3-dev-v1" | Out-Null

# GIỮ CỬA SỔ NÀY CHẠY
$env:AIC_RUN_ID = "tv1-tv3-dev-v1"
$env:AIC_CONFIG = "configs\default.yaml"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8100
```

Kiểm tra (cửa sổ khác):
```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8100/health
```
Kỳ vọng: `200`, `"status":"degraded"` (đúng vì run rỗng) — không phải lỗi.

---

## Bước 4 — Thành viên 4 (`tv4\`): chạy pipeline tổng + API cho TV5

### 4.1. Cài đặt

```powershell
cd D:\aic226\tv4
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

python -m pytest tests -q     # 19 test (13 pipeline + 6 API), không cần TV1/2/3
```

### 4.2. Cấu hình `tv4\configs\default.yaml`

File nằm ở `tv4\configs\default.yaml` → path tương đối resolve từ
`tv4\configs\`, cần `../../` để ra tới các thư mục ngang hàng `tv4\`:

```yaml
preprocess_run_id: run_v1_batch1

tv1:
  base_url: "http://127.0.0.1:8000"

tv3:
  base_url: "http://127.0.0.1:8100"

tv2_visual:
  enabled: true
  python_executable: "../../tv2_1/WP03/.venvs/coordinator/Scripts/python.exe"
  wp03_cwd: "../../tv2_1/WP03"
  artifact_root: "../../tv2_1/WP03/artifacts/smoke-run-1"
  runtime_root: "../../tv2_1/WP03"
  runtime_profile: "../../tv2_1/WP03/configs/runtime.windows.yaml"
  top_k: 100
  candidate_k_per_model: 200

tv2_refine:
  enabled: false
  python_executable: "../../tv2_1/WP09/.venv/Scripts/python.exe"
  wp09_cwd: "../../tv2_1/WP09"
  config_path: "../../tv2_1/WP09/configs/default.yaml"

fusion:
  rrf_k: 60
  dedup_window_ms: 1000
  top_k: 100

output_dir: "outputs"
```

Kiểm tra path resolve đúng trước khi chạy thật:
```powershell
python -c "from pathlib import Path; base=Path('configs'); p=(base/'../../tv2/WP03/.venvs/coordinator/Scripts/python.exe').resolve(); print(p, p.exists())"
```

### 4.3. Chạy CLI (một lần / theo lô)

Đảm bảo TV1 (port 8000) và TV3 (port 8100) đang chạy nền:

```powershell
python -m tv4 kis --config configs\default.yaml `
  --query "Tìm video về một diễn giả mặc áo đỏ phát biểu tại một cuộc họp báo ngoài trời, phía sau có nhiều cây xanh."

python -m tv4 qa --config configs\default.yaml `
  --query "video lễ trao giải thưởng âm nhạc" `
  --question "có bao nhiêu người lên sân khấu để nhận giải thưởng lớn nhất?"

python -m tv4 trake --config configs\default.yaml `
  --query "Tìm 4 khoảnh khắc chính khi vận động viên thực hiện cú nhảy: (1) giậm nhảy, (2) bay qua xà, (3) tiếp đất, (4) đứng dậy."

python -m tv4 batch --config configs\default.yaml --queries data\sample_queries.json --out outputs\
```

Output: KIS/VQA → CSV (`query_id, rank, video_id, frame_id[, answer]`); TRAKE
→ JSON (`{video_id, frame_ids: [...]}`).

### 4.4. Chạy API HTTP (mới — để TV5 gọi vào từ UI)

**Fixture mode** — TV5 dựng UI ngay, không cần TV1/TV2/TV3 chạy:
```powershell
$env:TV4_FIXTURE_MODE = "1"
python -m uvicorn tv4.api:app --host 127.0.0.1 --port 8200
```

**Live mode** — khi TV1/TV2/TV3 đã chạy thật:
```powershell
Remove-Item Env:\TV4_FIXTURE_MODE -ErrorAction SilentlyContinue
$env:TV4_CONFIG = "configs\default.yaml"
python -m uvicorn tv4.api:app --host 127.0.0.1 --port 8200
```

Kiểm tra: mở `http://127.0.0.1:8200/docs` (Swagger UI, tự sinh schema cho TV5) và:
```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8200/health
```

3 endpoint chính:
| Endpoint | Dùng cho |
|---|---|
| `POST /kis/search {query_text}` | Result grid top-100 |
| `POST /vqa/answer {query_text, question}` | Answer + evidence + confidence (top-5 candidate mặc định) |
| `POST /trake/align {query_text, events?}` | Timeline theo đúng thứ tự event |

---

## Tóm tắt thứ tự chạy mỗi lần làm việc (sau khi đã setup xong 1 lần)

```powershell
# Cửa sổ 1 — TV1
cd D:\aic226\tv1 ; .\.venv\Scripts\Activate.ps1
python wp06_api_server.py --run_dir data\runs\run_v1_batch1 --port 8000

# Cửa sổ 2 — TV3
cd D:\aic226\tv1tv3\TV1_TV3_WP04 ; .\.venv\Scripts\Activate.ps1
$env:AIC_RUN_ID = "tv1-tv3-dev-v1"; $env:AIC_CONFIG = "configs\default.yaml"
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8100

# Cửa sổ 3 — TV4 (API cho TV5; TV2 không cần chạy nền, wp03 search tự spawn subprocess)
cd D:\aic226\tv4 ; .\.venv\Scripts\Activate.ps1
$env:TV4_CONFIG = "configs\default.yaml"
python -m uvicorn tv4.api:app --host 127.0.0.1 --port 8200
```

(TV2 chỉ cần build lại index khi có video mới — không cần chạy nền.)

---

## Danh sách bug đã tìm và vá trong quá trình setup thật

| Repo | File | Bug | Trạng thái |
|---|---|---|---|
| TV1 | `tests/test_wp00.py` | Gọi `DataIntake(a,b,c)` — API cũ, implementation hiện tại nhận `DataIntake(config: dict)` | Đã bỏ qua bằng `--ignore`, chưa vá trong repo gốc |
| TV1 | `tests/test_wp06.py` | Import `AICApiServer` — class không tồn tại trong `wp06_api_server.py` | Đã bỏ qua bằng `--ignore`, chưa vá trong repo gốc |
| TV2 | `src/wp03/workers/{beit3,bge_vl,metaclip2,perception}.py` | Thiếu `if __name__ == "__main__": raise SystemExit(main())` | Đã vá |
| TV2 | `src/wp03/workers/perception.py` | `pe.CLIP.from_config(MODEL_ID, ...)` dùng nhầm HF repo_id thay vì tên config nội bộ `"PE-Core-B16-224"` | Đã vá |
| TV2 | `third_party/unilm/beit3/utils.py` (vendor) | `from torch._six import inf` — API đã bị xoá khỏi torch 2.x | Đã vá |
| TV4 | `src/tv4/cli.py::build_services()` | `python_executable` không resolve cùng cơ chế `base` như `wp03_cwd`/`artifact_root` | Đã vá |
| TV4 | `configs/default.yaml` | Thiếu 1 cấp `../` — path tính từ `tv4/configs/` chứ không phải `tv4/` | Đã vá |
| TV4 | `src/tv4/api.py` | Lỗi khởi tạo config/services trong `/kis/search`, `/vqa/answer`, `/trake/align` không được bọc `try/except` nhất quán như `/health` | Đã vá |

---

## Việc còn lại trước khi bàn giao chính thức cho TV5

1. Đổi `TV4_CORS_ORIGINS` sang domain thật của Vite dev server (mặc định `*`, chỉ dùng lúc dev).
2. Cắm VLM/LLM thật vào `RuleBasedFallbackEngine` trong `api.py::vqa_answer()` (đã đánh dấu `# TODO(TV4)` trong code) trước khi TV5 demo VQA.
3. TV5 dùng `submission.py` làm CLI fallback nộp bài — không cần code thêm, đã đúng format BTC.
