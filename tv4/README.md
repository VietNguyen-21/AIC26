# TV4 — Query Router, Multimodal Fusion, KIS/VQA/TRAKE (WP07, WP10, WP11, WP12)

> **Owner:** Thành viên 4
> **Vị trí sau khi giải nén:** đặt ngang hàng với `tv1/`, `tv2/`, `tv1tv3/` (cùng một thư mục cha).

TV4 là lớp điều phối cuối: nhận query thô (KIS/VQA/TRAKE) → route sang các
retriever độc lập của TV2 (visual) và TV3 (ocr/asr/object/metadata, trong
`tv1tv3.zip`) → hợp nhất bằng RRF → (tuỳ chọn) tinh chỉnh frame chính xác qua
WP09 → xuất kết quả đúng định dạng nộp bài của BTC.

TV4 **không tự làm lại** preprocessing, visual embedding hay OCR/ASR — nó chỉ
gọi API/CLI mà TV1/TV2/TV3 đã cung cấp, đúng như "Input nhận" trong
`AIC_2026_PLAN.xlsx` mô tả.

## 1. Kiến trúc

```
src/tv4/
  contracts.py           # SearchRequest / SearchCandidate / EvidencePack — khớp field-by-field
                          # với tv1tv3/.../contracts.py và tv2/WP03/.../contracts.py
  clients/
    tv1_client.py         # HTTP -> tv1/wp06_api_server.py (frames, keyframe image, validate)
    tv3_client.py         # HTTP -> tv1tv3 FastAPI backend (/text,/ocr,/asr,/object,/metadata search)
    tv2_visual_client.py  # subprocess -> `python -m wp03 search` (venv riêng của WP03)
    tv2_refine_client.py  # subprocess -> `python -m wp09 refine` (venv riêng của WP09)
  adapters/
    wp09_adapter.py        # decoder/scorer factory mà WP09 cần nhưng chưa ai viết; TV4 cung cấp
  wp07_router.py            # WP07: phân loại query, quyết định nhánh nào cần gọi
  wp10_fusion.py            # WP10: Reciprocal Rank Fusion + dedup + diversity cap top-100
  kis_pipeline.py           # Orchestrate KIS end-to-end (+ optional WP09 refine top-N)
  wp11_vqa.py                # WP11: EvidencePack, AnswerEngine (pluggable LLM/VLM), verifier, normalize
  wp12_trake.py              # WP12: event alignment (DP tối ưu theo ràng buộc thời gian tăng dần, + greedy fallback)
  trake_pipeline.py          # Orchestrate TRAKE end-to-end (2 giai đoạn: Retrieval -> Alignment)
  submission.py              # Xuất CSV/JSON đúng format nộp bài (rank quan trọng vì Final Score = mean(R@1,5,20,50,100))
  cli.py, __main__.py        # `python -m tv4 kis|qa|trake|batch`
configs/default.yaml
tests/                      # 13 unit test cho router/fusion/trake (pytest, không cần GPU/model)
```

### Vì sao gọi qua API/subprocess thay vì import trực tiếp?
- TV2's WP03/WP08/WP09 cần **venv GPU riêng cho từng model** (4 model stack
  không được cài chung — README của WP03 nói rõ điều này), nên TV4 gọi chúng
  qua CLI đã có sẵn (`python -m wp03 search`, `python -m wp09 refine`) thay
  vì import trong cùng process.
- TV3 (trong `tv1tv3.zip`) đã chủ động expose 5 endpoint HTTP cho đúng mục
  đích này (mục "7. TV4 consumer contract" trong README của họ).
- TV1 expose WP06 API cho đúng mục đích tương tự.

Nhờ vậy, TV4 tự nó **chỉ cần Python + PyYAML**, chạy được ngay cả khi máy này
chưa cài PyTorch/FAISS/model gì cả — các thành phần nặng chỉ cần chạy đúng
lúc TV1/TV2/TV3 cần chúng.

## 2. Giới hạn hiện tại (nói thẳng, không giấu)

- **WP09 exact-frame refine mặc định TẮT** (`tv2_refine.enabled: false` trong
  config) vì `adapters/wp09_adapter.py` hiện dùng **raw PTS làm frame_id tạm
  thời** cho các frame nằm giữa 2 keyframe — do `tv1/wp06_api_server.py`
  hiện chỉ expose danh sách keyframe (`/frames/{video_id}`), chưa có endpoint
  resolver full-resolution theo đúng nguyên tắc "frame_id không được suy ra
  từ fps" mà `tv1tv3` yêu cầu. Khi TV1 bổ sung endpoint đó, chỉ cần sửa
  `_resolve_frame_id` trong file adapter — không cần đổi gì ở phía TV4 khác.
- **WP03 (visual) của TV2 có 4 model, trong đó BEiT-3 đang bị khoá** (theo
  ghi chú làm việc gần đây) cho tới khi worker đó được xác thực nội bộ —
  `tv2_visual_client.py` xử lý việc này gracefully: nếu `wp03 search` lỗi
  hoặc model thiếu, nhánh visual trả về danh sách rỗng thay vì crash toàn
  pipeline (RRF tự động chỉ dùng các nhánh còn lại).
- **VQA answer engine mặc định là `RuleBasedFallbackEngine`** (chỉ trả lời
  khi tìm thấy chuỗi khớp trực tiếp trong OCR/ASR, còn lại đánh dấu
  `manual_review=True`). Đây là chỗ cắm VLM/LLM thật (ví dụ Qwen2.5-VL hoặc
  Qwen2.5-7B-Instruct đang dùng cho pipeline NER) — implement lại
  `AnswerEngine.answer()/verify()` trong `wp11_vqa.py` và truyền engine đó
  vào `answer_query(...)` (xem `cli.py::_cmd_qa` để biết chỗ inject).

## 3. Cài đặt

```powershell
cd tv4
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 4. Chạy test (không cần GPU, không cần TV1/2/3 đang chạy)

```powershell
python -m pytest tests -q
```

## 5. Cấu hình

Sửa `configs/default.yaml`:
- `tv1.base_url` — nơi `tv1/wp06_api_server.py` đang chạy.
- `tv3.base_url` — nơi backend FastAPI của `tv1tv3` đang chạy (uvicorn).
- `tv2_visual.*` — đường dẫn tới python trong venv của WP03 và `artifact_root`
  (thư mục chứa index đã build).
- `tv2_refine.*` — tương tự cho WP09, giữ `enabled: false` cho tới khi đã
  đọc mục 2 ở trên.

## 6. Chạy

```powershell
# Textual KIS
python -m tv4 kis --config configs/default.yaml --query "Tìm video về một diễn giả mặc áo đỏ phát biểu tại một cuộc họp báo ngoài trời, phía sau có nhiều cây xanh."

# Q&A
python -m tv4 qa --config configs/default.yaml --query "video lễ trao giải thưởng âm nhạc" --question "có bao nhiêu người lên sân khấu để nhận giải thưởng lớn nhất?"

# TRAKE
python -m tv4 trake --config configs/default.yaml --query "Tìm 4 khoảnh khắc chính khi vận động viên thực hiện cú nhảy: (1) giậm nhảy, (2) bay qua xà, (3) tiếp đất, (4) đứng dậy."

# Batch (đọc data/sample_queries.json làm mẫu)
python -m tv4 batch --config configs/default.yaml --queries data/sample_queries.json --out outputs/
```

Output:
- KIS → CSV `query_id, rank, video_id, frame_id` (rank 1 = ứng viên tốt nhất — **thứ tự quan trọng** vì Final Score BTC tính theo R@1/5/20/50/100).
- VQA → CSV thêm cột `answer`, `manual_review`.
- TRAKE → JSON `{video_id, frame_ids: [...]}` theo đúng thứ tự event.

Xem hướng dẫn chạy **toàn bộ pipeline 4 thành viên** (từ cài đặt tới chạy
thật) ở file `END_TO_END_GUIDE.md` cùng cấp với thư mục này (do TV4 biên
soạn, đặt ở thư mục cha chứa cả tv1/tv2/tv1tv3/tv4).
