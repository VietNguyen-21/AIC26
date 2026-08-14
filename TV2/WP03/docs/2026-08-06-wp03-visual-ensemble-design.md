# WP03 — Thiết kế Visual Ensemble Retrieval

**Ngày:** 2026-08-06  
**Phụ trách:** TV2 — Tấn  
**Người chạy GPU và nghiệm thu smoke test:** TV4 — Việt  
**Trạng thái:** Đã cập nhật theo review; chờ xác nhận trước khi lập kế hoạch TDD

## 1. Mục tiêu và phạm vi

WP03 xây dựng tầng truy hồi thị giác độc lập, đọc trực tiếp artifact do pipeline TV1 bàn giao. Hệ thống mã hóa keyframe bằng bốn model, tạo bốn FAISS index riêng, truy hồi từng index rồi hợp nhất thứ hạng bằng Reciprocal Rank Fusion (RRF). Đầu ra cuối cùng là **một danh sách ứng viên thuộc nguồn `visual`** để TV4 tiếp tục fusion với OCR, ASR hoặc các nguồn khác.

WP03 không sửa mã nguồn TV1, không tái sử dụng WP03/WP08/WP09 có trong `TV1.zip`, không trích xuất frame từ video và không thực hiện fusion đa phương thức cuối cùng.

## 2. Các quyết định đã chốt

- Viết một Python package độc lập trong thư mục `WP03`.
- Dùng một orchestrator trung tâm và bốn worker model cách ly phụ thuộc.
- Mỗi model có embedding, mapping, FAISS index và manifest riêng.
- Truy hồi văn bản trên cả bốn model, sau đó RRF với `k=60`.
- Khóa model/repository bằng revision đầy đủ; không dùng nhánh động như `main`, `master` hoặc `latest` ở runtime.
- Chạy tuần tự từng model để phù hợp GPU RTX 5070 Ti 12 GB.
- Tấn viết code, config, test CPU và tài liệu. Việt chạy smoke/full trên máy GPU.
- Smoke test dùng ba video `L21_V001`, `L21_V002`, `L21_V003`; full run dùng toàn corpus mà TV1 bàn giao.
- Mọi đường dẫn dữ liệu là tương đối với `--data-root`; không hard-code đường dẫn máy cá nhân.

## 3. Kiến trúc

```text
TV1 frames.jsonl + keyframe files
                  |
                  v
          WP03 orchestrator
        /        |        |        \
   BEiT-3     BGE-VL   MetaCLIP2    PE
      |          |         |         |
 embeddings + mapping + FAISS index (riêng từng model)
        \        |         |        /
                  v
             RRF (k=60)
                  |
                  v
       một ranked list source=visual
```

Orchestrator sở hữu toàn bộ logic dùng chung: đọc/kiểm tra contract TV1, chia shard, resume, checksum, tạo mapping, xây FAISS index, quản lý manifest, truy vấn và RRF. Worker chỉ sở hữu adapter model và thao tác encode ảnh/văn bản. Ranh giới này giữ pipeline nhất quán trong khi tránh xung đột dependency giữa bốn model.

Worker được gọi bằng subprocess. Giao thức trao đổi chỉ gồm JSON và file NumPy, không truyền tensor hoặc object Python qua process boundary.

## 4. Model và revision

| Model key | Model/checkpoint | Revision pin | Nguồn chính thức | Chính sách chạy |
|---|---|---|---|---|
| `beit3` | BEiT-3 Base COCO Retrieval 384×384, khởi tạo từ Base ITC | UniLM `833df7e7832e5064a281131ee64a481afa8e5b95` | [Microsoft UniLM — BEiT-3](https://github.com/microsoft/unilm/tree/833df7e7832e5064a281131ee64a481afa8e5b95/beit3) | worker riêng; checkpoint `beit3_base_patch16_384_coco_retrieval.pth` |
| `bge_vl` | `BAAI/BGE-VL-large` | `40fb48217f521df22a2a5bf15edd52ed1146ef05` | [BAAI BGE-VL-large](https://huggingface.co/BAAI/BGE-VL-large/tree/40fb48217f521df22a2a5bf15edd52ed1146ef05) | `trust_remote_code=True`, revision bắt buộc |
| `metaclip2` | `facebook/metaclip-2-worldwide-huge-quickgelu` | `c139061af7b10fdb2e754b60d2b1182a3d5526c2` | [MetaCLIP2 Worldwide Huge](https://huggingface.co/facebook/metaclip-2-worldwide-huge-quickgelu/tree/c139061af7b10fdb2e754b60d2b1182a3d5526c2) | BF16 ưu tiên, FP16 fallback, batch nhỏ và chạy tuần tự |
| `perception` | `facebook/PE-Core-B16-224` | `a16450b46fef32363459920c2685a1b4ef13dcd9` | [Perception Encoder Core B/16](https://huggingface.co/facebook/PE-Core-B16-224/tree/a16450b46fef32363459920c2685a1b4ef13dcd9) | BF16 ưu tiên, FP16 fallback |

Đây là lựa chọn triển khai của đội dựa trên bốn họ model mà bài Top 2 AIC 2025 công bố. Bài báo không công bố đủ checkpoint, revision, batch size, index type hoặc tham số RRF để tái tạo nguyên xi; vì vậy các giá trị trên phải được ghi rõ trong manifest để kết quả có thể truy vết.

Mỗi worker phải nạp đúng revision trong config. Nếu backend không hỗ trợ truyền revision trực tiếp, worker phải kiểm tra repository/checkpoint đã checkout ở đúng commit trước khi encode. Không tự động nâng revision.

Checkpoint BEiT-3 dùng URL release chính thức `https://github.com/addf400/files/releases/download/beit3/beit3_base_patch16_384_coco_retrieval.pth`, kích thước công bố qua GitHub Release API là `445025515` byte. Lệnh `lock-model` phải kiểm tra đúng kích thước, tính SHA-256 từ file đã được đội xác nhận tin cậy rồi ghi `model-locks/beit3.json`; worker từ chối nạp model khi lock thiếu, size sai hoặc digest sai. Không bịa SHA-256 trong source trước khi có file tin cậy. Những lần chạy sau chỉ dùng file có digest trùng cache lock; đổi digest cần thao tác relock rõ ràng, không được chấp nhận ngầm.

## 5. Contract đầu vào từ TV1

Lệnh build nhận:

- `--data-root`: thư mục gốc chứa dữ liệu/artifact.
- `--frames`: đường dẫn tương đối tới `frames.jsonl`.
- `--run-id`: định danh run đầu ra của WP03.
- `--config`: `configs/smoke.yaml` hoặc `configs/full.yaml`.

Mỗi dòng `frames.jsonl` phải là một JSON object có tối thiểu:

```json
{
  "preprocess_run_id": "tv1-run-id",
  "video_id": "L21_V001",
  "frame_id": 42,
  "keyframe_seq": 7,
  "timestamp_ms": 12345,
  "pts": 296280,
  "time_base": "1/24000",
  "decode_index": 296,
  "shot_id": "L21_V001_S0007",
  "keyframe_path": "keyframes/L21_V001/000042.jpg"
}
```

Các trường khác của TV1 được chấp nhận và bỏ qua nếu WP03 không dùng. `keyframe_path` được resolve dưới `--data-root` và không được thoát ra ngoài data root. Một bản ghi bị xem là không hợp lệ khi thiếu trường bắt buộc, trùng khóa `(video_id, frame_id)`, đường dẫn không tồn tại, hoặc các bản ghi trong cùng build có `preprocess_run_id` khác nhau. Lỗi contract làm dừng build trước khi gọi GPU.

Thứ tự chuẩn của corpus là `(video_id, frame_id)` tăng dần, không phụ thuộc thứ tự dòng trong JSONL. Thứ tự này được dùng thống nhất cho shard và mapping.

## 6. Contract artifact đầu ra

```text
WP03/artifacts/<run_id>/
  embeddings/
    <model>/shard-00000.npy
  embedding_maps/
    <model>.parquet
    <model>.jsonl              # debug export, không phải contract canonical
  indexes/
    <model>.faiss
  manifests/
    <model>.json
  reports/
    build-summary.json
```

`embedding_maps/<model>.parquet` là artifact canonical để tích hợp. Mỗi record có đúng một vector và tuân thủ `EmbeddingMapRecord` chung, cộng thêm `keyframe_path` tương đối (POSIX) để WP03 tra evidence không cần suy đoán từ tên file:

```json
{
  "schema_version": "1.0.0",
  "preprocess_run_id": "tv1-run-id",
  "model_name": "bge_vl",
  "model_version": "40fb48217f521df22a2a5bf15edd52ed1146ef05",
  "vector_id": 0,
  "video_id": "L21_V001",
  "frame_id": 42,
  "keyframe_seq": 7,
  "timestamp_ms": 12345,
  "embedding_dim": 1024,
  "vector_dtype": "float32",
  "l2_normalized": true,
  "keyframe_path": "keyframes/L21_V001/000042.jpg",
  "created_at_utc": "2026-08-06T00:00:00Z"
}
```

`vector_id` phải liên tục từ `0` và khớp row trong index. Không suy ra mapping từ tên file. JSONL, nếu được xuất, phải có nội dung logic tương đương Parquet và chỉ phục vụ debug/inspection.

Manifest từng model chứa tối thiểu:

- schema version và trạng thái `complete`, `failed` hoặc `disabled`;
- model key, model/checkpoint ID, revision đầy đủ;
- preprocessing parameters, image size, dtype và normalization;
- embedding dimension, metric, index type và số vector;
- `preprocess_run_id`, WP03 `run_id`, thời điểm bắt đầu/kết thúc;
- config digest, input JSONL digest, corpus content digest, mapping digest và index digest;
- compatibility/runtime fingerprint, image/text preprocess digest, tokenizer revision, query template và compute dtype thực tế;
- content validation mode `fast` hoặc `strict`;
- danh sách shard, shard input digest, shape, dtype và SHA-256;
- lỗi đã chuẩn hóa nếu model thất bại.

`build-summary.json` tổng hợp trạng thái bốn model. Build thành công khi ít nhất một model hoàn tất; build thất bại khi không model nào hoàn tất. Thành công suy giảm phải được đánh dấu `degraded: true`, không được im lặng bỏ model lỗi.

Artifact được ghi vào file tạm cùng thư mục rồi rename nguyên tử sau khi kiểm tra. Manifest `complete` chỉ được ghi sau cùng.

Kết quả search dùng envelope tương thích pipeline chung:

```json
{
  "schema_version": "1.0.0",
  "query_id": "generated-or-upstream-id",
  "wp03_run_id": "wp03-run-id",
  "preprocess_run_id": "tv1-run-id",
  "degraded": false,
  "models_requested": ["beit3", "bge_vl", "metaclip2", "perception"],
  "models_used": ["beit3", "bge_vl", "metaclip2", "perception"],
  "requested_top_k": 100,
  "returned_count": 100,
  "candidate_k_per_model": 200,
  "hard_candidate_cap": null,
  "candidates": []
}
```

WP03 nhận `query_id` và `event_index` từ `SearchRequest` khi TV4 gọi. Với CLI độc lập, WP03 tạo UUID cho `query_id` và đặt `event_index` là `null`.

## 7. Worker protocol

Orchestrator gửi cho worker một request JSON qua file:

```json
{
  "schema_version": "1.0.0",
  "job_id": "uuid-v4",
  "request_sha256": "<64 lowercase hex characters>",
  "operation": "encode_images",
  "model_key": "bge_vl",
  "revision": "40fb48217f521df22a2a5bf15edd52ed1146ef05",
  "device": "cuda",
  "dtype": "bfloat16",
  "batch_size": 4,
  "attempt": 1,
  "items": [
    {"item_id": 0, "image_path": "C:/resolved/path/000042.jpg"}
  ],
  "output_path": "C:/resolved/path/job-uuid.output.npy.tmp",
  "status_path": "C:/resolved/path/job-uuid.status.json"
}
```

Worker trả status JSON:

```json
{
  "schema_version": "1.0.0",
  "job_id": "uuid-v4",
  "request_sha256": "<64 lowercase hex characters>",
  "status": "ok",
  "count": 1,
  "dimension": 1024,
  "dtype": "float32",
  "normalized": true,
  "sha256": "<64 lowercase hex characters>",
  "compatibility_fingerprint": "<64 lowercase hex characters>",
  "runtime_fingerprint": "<64 lowercase hex characters>",
  "started_at_utc": "2026-08-06T00:00:00Z",
  "finished_at_utc": "2026-08-06T00:00:01Z"
}
```

`request_sha256` là SHA-256 của request JSON canonical sau khi bỏ chính field `request_sha256`. `batch_size` phải dương; `attempt` bắt đầu từ `1` và tăng khi BF16 fallback hoặc OOM retry. Hai field này được ghi vào status/manifest để audit. `WorkerRequest.create(job_dir, ...)` là chủ sở hữu duy nhất của đường dẫn job: nó tạo `<job_dir>/<job_id>.request.json`, `<job_dir>/<job_id>.output.npy.tmp` và `<job_dir>/<job_id>.status.json`; caller không tự truyền các path này. Status cùng `job_id` là bắt buộc. Orchestrator kiểm tra `job_id`, `request_sha256`, timestamp, `status_path` và timeout trước khi đọc output, rồi mới rename output vào artifact chính thức, nên status cũ không thể bị dùng nhầm.

Mỗi worker được khai báo trong runtime profile, không hard-code đường dẫn máy:

```yaml
workers:
  bge_vl:
    python: ".venvs/bge_vl/Scripts/python.exe"
    module: "wp03.workers.bge_vl"
    model_cache_root: "model-cache/bge_vl"
```

Profile `windows` dùng `Scripts/python.exe`; profile `linux` dùng `.venvs/<model>/bin/python`. Cả hai path được resolve tương đối với `--runtime-root`. Worker entrypoint được chạy từ source tree đã checkout nên bốn environment nạp cùng version mã WP03 nhưng chỉ import dependency model trong process của chính nó.

Với `encode_text`, request chứa `texts` và output là ma trận `(n_queries, dimension)`. Mỗi worker phải dùng đúng tokenizer, revision, query template và normalization đã khai báo. V1 giữ nguyên query, chuẩn hóa Unicode NFC, trim whitespace, từ chối query rỗng sau normalize và không tự dịch Việt–Anh. Query template mặc định là chuỗi rỗng; mọi thay đổi template là thay đổi config.

Embedding lưu ra artifact và đưa vào FAISS luôn là `float32`, L2-normalized, bất kể compute dtype của worker. Worker phải trả exit code khác `0` và status lỗi có `error_type`, `message`, `retryable` khi thất bại.

`compatibility_fingerprint` là SHA-256 của JSON canonical gồm model/checkpoint revision, tokenizer revision, hash mã adapter, image/text preprocessing, query template, embedding dimension và normalization semantics. `runtime_fingerprint` bao gồm `compatibility_fingerprint` cùng package versions đã pin, device, compute dtype, PyTorch/CUDA environment. Manifest lưu cả hai fingerprint, `image_preprocess_digest`, `text_preprocess_digest`, tokenizer revision, query template và compute dtype thực tế.

Khi search, model chỉ được dùng khi index manifest là `complete`, compatibility fingerprint và text preprocess digest từ worker khớp manifest, dimension khớp và text embedding hợp lệ. Khác runtime fingerprint chỉ tạo cảnh báo audit; BF16 build và FP16 fallback ở search vẫn compatible khi các điều kiện ngữ nghĩa còn lại khớp. Một text worker fail tạo search degraded; bốn text worker fail làm search thất bại.

Orchestrator không parse log tự do để quyết định trạng thái; quyết định chỉ dựa trên exit code, status JSON và kiểm tra artifact.

## 8. Shard, resume và tính xác định

- Shard theo số record cố định trong config; smoke mặc định `64`, full mặc định `512`.
- Mỗi shard ghi `item_id` theo corpus order chuẩn.
- `frames_jsonl_digest` là SHA-256 byte-level của file input. `corpus_content_digest` đại diện nội dung corpus đã chọn theo corpus order, không phải chỉ đường dẫn file.
- `fast` mode ưu tiên digest của manifest TV1 đã validated khi `--tv1-manifest` được cung cấp. Nếu không có manifest, fallback `corpus_content_digest = SHA256(preprocess_run_id || frames_jsonl_digest || canonical_selected_records)` và ghi `content_integrity_source: frames_jsonl_fallback` trong manifest. Fast mode không đọc byte ảnh; nó phù hợp khi artifact TV1 là bất biến.
- `strict` mode tạo `record_content_digest = SHA256(canonical_record || SHA256(image_bytes))`; canonical record gồm `preprocess_run_id`, `video_id`, `frame_id`, `keyframe_seq`, `timestamp_ms` và `keyframe_path` chuẩn hóa POSIX. `corpus_content_digest` là SHA-256 của chuỗi `record_content_digest` theo corpus order; `shard_input_digest` được tính tương tự trên đúng record của shard.
- Strict mode phải đọc byte ảnh trước khi quyết định reuse shard. Digest chỉ sống ở corpus/shard manifest; không được lặp `image_sha256` vào `EmbeddingMapRecord`.
- Resume chỉ tái sử dụng shard khi content validation mode, config digest, model revision, compatibility fingerprint, shard input digest, shape, dtype và output SHA-256 đều khớp. Runtime fingerprint khác được ghi audit nhưng không tự invalid shard.
- Shard thiếu hoặc sai checksum được encode lại; không nối tiếp một phần file `.npy`.
- Đổi filter video, corpus order, validation mode hoặc bất kỳ content digest nào làm invalid shard liên quan.
- Sau khi đủ shard, orchestrator kiểm tra số row bằng mapping và xây index theo streaming; không concatenate toàn bộ embedding corpus.
- Cùng input, config và revision phải tạo mapping cùng thứ tự. Sai số vector phụ thuộc backend GPU nhưng không được làm thay đổi mapping.

## 9. FAISS và truy hồi

Phiên bản đầu dùng exact cosine search để có baseline dễ kiểm chứng:

- normalize vector ảnh và text bằng L2;
- `IndexFlatIP` cho từng model;
- điểm FAISS là inner product tương đương cosine similarity sau normalization;
- không huấn luyện index và không có tham số ngẫu nhiên;
- `candidate_k_per_model` mặc định `200` trong full config và `20` trong smoke config.
- Full run dùng `per_model_limit = min(index_size, max(requested_top_k, candidate_k_per_model))`. Smoke có `hard_candidate_cap: 20`, nên response luôn ghi `requested_top_k` và `returned_count` để caller biết kết quả bị cap.

Index được dựng tuần tự theo model và theo shard: mở từng `.npy` bằng memory-map, kiểm tra từng block rồi `index.add(block)`. `IndexFlatIP` vẫn giữ toàn index của **một model** trong RAM; streaming chỉ loại ma trận concatenate và các bản sao trung gian. Trước build, WP03 xuất preflight report gồm `estimated_embedding_disk_bytes`, `estimated_index_ram_bytes`, `available_disk_bytes` và `available_ram_bytes`; build dừng trước GPU nếu không đủ tài nguyên theo margin config.

Search cũng xử lý tuần tự: encode query của một worker, mở index tương ứng, lấy ranked candidates, giải phóng index/worker resources rồi chuyển model tiếp theo. Không load đồng thời bốn index. Với mỗi model, kết quả được stable-sort theo `similarity` giảm dần rồi `vector_id` tăng dần trước khi gán rank.

API lõi:

```python
search_text(query: str, k: int) -> list[SearchCandidate]
```

Mỗi candidate tuân thủ đầy đủ contract chung:

```json
{
  "schema_version": "1.0.0",
  "query_id": "generated-or-upstream-id",
  "event_index": null,
  "rank": 1,
  "source": "visual",
  "video_id": "L21_V001",
  "frame_id": 42,
  "timestamp_ms": 12345,
  "raw_score": null,
  "score": 0.0312,
  "model_scores": {"beit3": 0.41, "bge_vl": 0.37},
  "model_ranks": {"beit3": 2, "bge_vl": 5},
  "matched_filters": [],
  "evidence_refs": ["keyframe:keyframes/L21_V001/000042.jpg"],
  "confidence": null,
  "preprocess_run_id": "tv1-run-id",
  "created_at_utc": "2026-08-06T00:00:00Z"
}
```

`score` là RRF score; `raw_score` luôn `null` vì WP03 không có một raw score chung. `model_scores` chỉ phục vụ audit, mỗi giá trị vẫn là similarity của model tương ứng. Không trộn raw similarity giữa các model.

## 10. RRF

Khóa gộp là `(video_id, frame_id)`. Với tập model hoàn tất `M`, điểm:

```text
rrf_score(document) = sum(1 / (60 + rank_m(document))) for m in M
```

`rank_m` bắt đầu từ `1`. Tập `M` chỉ gồm model có index complete **và** encode text thành công trong chính query đó. Một document không xuất hiện trong danh sách của model không được cộng điểm từ model đó. Kết quả sắp xếp theo:

1. `rrf_score` giảm dần;
2. số model bỏ phiếu giảm dần;
3. `video_id` tăng dần;
4. `frame_id` tăng dần.

Tie-break cố định làm kết quả tái lập. `model_ranks` chỉ ghi các model thực sự trả document. Nếu một model failed/disabled, RRF chạy trên các model còn lại và response phải kèm trạng thái degraded ở metadata cấp truy vấn.

## 11. Cấu hình smoke và full

`configs/smoke.yaml`:

- chỉ chọn `L21_V001`, `L21_V002`, `L21_V003`;
- mỗi model chạy tuần tự;
- shard size `64`, candidate k `20`;
- batch size khởi điểm `1` cho MetaCLIP2, `4` cho ba model còn lại;
- ưu tiên BF16 trên CUDA, fallback FP16 nếu adapter không hỗ trợ BF16;
- CPU test không nạp model thật.

Smoke dùng `content_validation_mode: strict`. Một smoke pass để merge yêu cầu: cả bốn model có manifest `complete`; integrity của mapping/index/shard pass; và tối thiểu ba query encode/search/RRF thành công. Smoke degraded chỉ là test chịu lỗi, không phải điều kiện merge. Ngoại lệ merge chỉ hợp lệ khi cả đội ghi quyết định rõ trong issue/PR kèm manifest lỗi tái hiện được.

`configs/full.yaml`:

- không lọc video;
- shard size `512`, candidate k `200`;
- batch size mặc định giữ nguyên smoke: `1` cho MetaCLIP2, `4` cho ba model còn lại; chỉ tăng bằng thay đổi config sau khi smoke test của Việt chứng minh ổn định;
- model vẫn chạy tuần tự, giải phóng worker/process trước khi chuyển model.

OOM không tự động giảm batch vô hạn. Worker OOM bị hủy; orchestrator khởi tạo process mới để retry đúng một lần: nếu batch ban đầu lớn hơn `1`, dùng nửa batch; nếu là `1`, retry clean-process vẫn với batch `1`. Retry còn OOM thì model failed và pipeline tiếp tục model kế tiếp. Mọi retry được ghi trong manifest.

## 12. Giao diện CLI

```text
python -m wp03 validate --data-root <root> --frames <relative-jsonl>
python -m wp03 build --data-root <root> --frames <relative-jsonl> \
  --run-id <id> --config configs/smoke.yaml \
  --runtime-root <runtime-root> --runtime-profile windows \
  --content-validation strict
python -m wp03 search --artifact-root artifacts/<run-id> \
  --query "a red car at an intersection" --top-k 100 \
  --runtime-root <runtime-root> --runtime-profile windows
python -m wp03 inspect --artifact-root artifacts/<run-id>
```

CLI trả exit code `0` cho build/search thành công đầy đủ hoặc degraded có ít nhất một model usable; exit code khác `0` cho lỗi contract, cấu hình, artifact hoặc khi cả bốn model thất bại. Lệnh `search` in envelope JSON ở mục 6. `build-summary.json` là nguồn sự thật chi tiết, không dựa vào console text.

## 13. Xử lý lỗi và an toàn dữ liệu

- Validate toàn bộ input trước khi khởi chạy model.
- Lỗi một model không xóa artifact complete của model khác.
- Không ghi đè artifact complete của cùng `run_id` nếu không có `--resume`; yêu cầu run ID mới.
- `--resume` chỉ dùng quy tắc checksum ở mục 8.
- Từ chối `keyframe_path` absolute, drive path, UNC path, path traversal hoặc symlink escape; chỉ serialize path tương đối với POSIX separator `/`.
- `run_id` chỉ cho phép chữ, số, `.`, `_` và `-`.
- Không tự tải model khi `offline: true`; báo rõ cache nào đang thiếu.
- Không ghi token, biến môi trường hoặc absolute data path vào manifest/log chia sẻ.
- Log chứa model, shard, elapsed time, retry và trạng thái nhưng không chứa dữ liệu bí mật.

## 14. Kiểm thử và tiêu chí nghiệm thu

### Test CPU bắt buộc

1. Parser chấp nhận fixture hợp lệ theo contract TV1.
2. Parser từ chối trường thiếu, key trùng, mixed `preprocess_run_id`, absolute/drive/UNC path, path traversal, symlink escape và file thiếu.
3. Corpus order và mapping ổn định khi đảo thứ tự dòng JSONL.
4. Fast/strict tạo digest đúng; byte ảnh đổi nhưng JSONL không đổi phải invalid shard trong strict mode.
5. Filter video hoặc thứ tự corpus đổi phải invalid đúng shard; resume chỉ bỏ qua shard có `shard_input_digest` và output checksum hợp lệ.
6. Fake worker tạo embedding xác định; orchestrator kiểm tra 2-D shape, row count, dimension, float32, NaN/Inf, zero vector, L2 norm tolerance và checksum.
7. Hai shard khác dimension hoặc index `ntotal` khác mapping count không được tạo manifest `complete`.
8. FAISS streaming mapping trả đúng `(video_id, frame_id)` mà không concatenate toàn corpus.
9. RRF đúng công thức, xử lý document thiếu ở một model và tie-break ổn định.
10. Compatibility/text fingerprint không khớp làm model bị loại; runtime fingerprint hoặc BF16/FP16 khác nhưng compatibility khớp không được loại model; một text worker fail tạo search degraded, bốn worker fail tạo search failed.
11. Một model build thất bại tạo build degraded; bốn model thất bại tạo build failed.
12. Status cũ khác `job_id`, timeout, temp file sau interrupted build, index/mapping digest bị sửa đều không được xem là artifact hợp lệ.
13. OOM retry dùng process mới đúng một lần, nửa batch khi batch lớn hơn một; BF16 không hỗ trợ fallback một lần sang FP16 bằng process mới.
14. Worker status path/job ID stale và output temp file không được xem là artifact hợp lệ.
15. BEiT-3 checkpoint lock từ chối lock thiếu, size sai hoặc SHA-256 sai trước khi adapter nạp model.
16. CLI trả đúng exit code, response envelope, `requested_top_k`/`returned_count`, `--tv1-manifest` fast fallback và schema `SearchCandidate` đầy đủ.

Test dùng ảnh fixture nhỏ và fake worker, không cần model thật hoặc GPU. Các test hành vi được viết trước implementation theo chu trình red–green–refactor.

### Smoke test GPU do Việt chạy

1. Checkout code của Tấn trên feature branch.
2. Chuẩn bị artifact TV1 cho ba video đã chọn.
3. Cài từng worker environment từ lockfile tương ứng.
4. Chạy `validate`, sau đó `build` với smoke config.
5. Xác nhận cả bốn manifest `complete`, integrity mapping/index/shard pass; nếu bất kỳ model lỗi, smoke chỉ được ghi là degraded và không merge.
6. Chạy tối thiểu ba text query; kiểm tra response đầy đủ schema, kết quả map về keyframe có thật và `models_used` gồm đủ bốn model.
7. Gửi lại `build-summary.json`, bốn manifest, peak VRAM và thời gian chạy; không gửi embedding/index qua Git.

### Definition of Done

- Toàn bộ test CPU pass trên máy không GPU.
- Không có đường dẫn máy cá nhân trong source/config/fixture.
- Bốn model/repository đều dùng revision đầy đủ.
- Artifact canonical dùng Parquet, mapping và SearchCandidate tuân theo schema trong đặc tả/pipeline chung.
- Resume tôn trọng `corpus_content_digest`, `shard_input_digest` và content validation mode.
- RRF `k=60` trả đúng một list `source=visual`.
- README đủ để Việt cài, chạy smoke và thu thập báo cáo mà không cần sửa source.
- Việt hoàn thành smoke đầy đủ: bốn manifest complete, integrity pass và ba query pass; chỉ merge sau điều kiện này.

## 15. Cấu trúc mã dự kiến

```text
WP03/
  pyproject.toml
  README.md
  configs/
    smoke.yaml
    full.yaml
  envs/
    beit3.txt
    bge_vl.txt
    metaclip2.txt
    perception.txt
  src/wp03/
    __init__.py
    __main__.py
    cli.py
    config.py
    contracts.py
    corpus.py
    artifacts.py
    worker_protocol.py
    orchestrator.py
    index.py
    fusion.py
    search.py
    workers/
      common.py
      beit3.py
      bge_vl.py
      metaclip2.py
      perception.py
  tests/
    fixtures/
    test_contracts.py
    test_orchestrator.py
    test_index.py
    test_fusion.py
    test_cli.py
```

Số file thực tế có thể cao hơn 15 vì bốn environment và adapter được tách riêng có chủ đích. Các module chung không được phụ thuộc framework model; adapter không được chứa logic RRF, mapping hoặc artifact lifecycle.

## 16. Những điểm cố ý chưa làm trong WP03 phiên bản đầu

- approximate FAISS index (IVF/HNSW/PQ);
- reranker học máy;
- fusion với OCR/ASR;
- web service hoặc giao diện người dùng;
- tự động dò batch size tối ưu;
- upload artifact lên storage từ xa;
- tái tạo chính xác các config không được công bố trong bài Top 2.

Các phần này chỉ được thêm sau khi baseline exact-search bốn model chạy ổn định và có số đo chất lượng/tài nguyên.
