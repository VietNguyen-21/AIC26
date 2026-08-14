# AIC 2026: Raw-Video-First Pipeline (Data Engine)

> **Owner:** Thành viên 1  
> **Status:** Stable (Sẵn sàng handover cho team Visual / AI)

Đây là nền móng dữ liệu (Data Intake & Preprocessing) cho dự án AIC 2026. Thay vì phụ thuộc vào dữ liệu được tiền xử lý sẵn, hệ thống này tự động trích xuất toàn bộ dữ liệu từ raw video, bao gồm kiểm tra tính toàn vẹn (Media Probe), trích xuất Keyframe thông minh, tạo cấu trúc không gian thời gian (Temporal) và cung cấp hệ thống API xác thực (Validation).

## 1. Yêu cầu hệ thống (Prerequisites)

- Python 3.10+
- FFmpeg (Yêu cầu phải được cài đặt và có trong PATH hệ thống).
- Các thư viện Python (Xem `requirements.txt`):
  ```bash
  pip install -r requirements.txt
  ```
  *(Các thư viện chính bao gồm: pandas, pyarrow, av, opencv-python, fastapi, uvicorn, numpy)*

## 2. Cấu trúc thư mục

```text
├── zip_video/                  # (Input) Thư mục chứa các file .zip video thô từ BTC
├── data/
│   ├── raw/                    # Video thô sau khi giải nén
│   └── runs/
│       └── run_v1_batch1/      # (Output) Thư mục chứa toàn bộ artifact sinh ra từ Pipeline
├── wp00_data_intake.py         # WP00: Giải nén & sinh Manifest
├── wp01_media_probe.py         # WP01: Kiểm tra metadata, decode, tách Audio
├── wp02_shot_keyframe.py       # WP02: Trích xuất Keyframe (Hybrid Shot + Max Gap)
├── wp05_temporal_adj.py        # WP05: Xây dựng liên kết thời gian (Temporal Windows)
├── wp06_api_server.py          # WP06: API Server & Validation Engine
└── README.md
```

## 3. Hướng dẫn chạy Pipeline (Tuần tự)

Để khởi tạo toàn bộ dữ liệu từ đầu, vui lòng chạy các scripts theo đúng thứ tự dưới đây:

### Bước 1: Data Intake (WP00)
Giải nén an toàn các file Zip, tạo mã băm SHA-256 để chống trùng lặp, và sinh ra danh sách `corpus_manifest.parquet`.
```bash
python wp00_data_intake.py --archives_dir zip_video --raw_dir data/raw --run_dir data/runs/run_v1_batch1
```

### Bước 2: Media Probe & Audio Prep (WP01)
Kiểm tra độ toàn vẹn của video (decode test), lấy metadata chính xác (duration, time_base) và tách file âm thanh `.wav` 16kHz mono. Quá trình tự động lưu checkpoint sau mỗi 10 videos để chống mất dữ liệu.
```bash
python wp01_media_probe.py --raw_dir data/raw --run_dir data/runs/run_v1_batch1 --preprocess_run_id run_v1_batch1
```

### Bước 3: Shot Detection & Keyframe Selection (WP02)
Tiến trình nặng nhất. Quét toàn bộ video để cắt shot, bắt frame bằng độ sắc nét (sharpness), giảm trùng lặp bằng pHash và **bảo toàn PTS (Presentation Timestamp) gốc**.
```bash
python wp02_shot_keyframe.py --raw_dir data/raw --run_dir data/runs/run_v1_batch1 --preprocess_run_id run_v1_batch1
```

### Bước 4: Temporal Adjacency (WP05)
Sắp xếp và tính toán các mốc thời gian (windows) bao quanh keyframe, cung cấp cấu trúc truy vấn prev/next cho các task VQA/TRAKE sau này.
```bash
python wp05_temporal_adj.py --run_dir data/runs/run_v1_batch1
```

---

## 4. Kiểm thử & Khởi chạy API (WP06)

Sau khi Pipeline chạy xong, bạn sử dụng WP06 để xác thực dữ liệu có đạt chuẩn hay không và bật Server cung cấp Data cho các module khác.

### Khởi chạy Server
```bash
python wp06_api_server.py --run_dir data/runs/run_v1_batch1 --port 8000
```

### Các Endpoints chính
- `GET /health`: Kiểm tra trạng thái server.
- `GET /summary`: Tổng quan số lượng video, frame và dung lượng.
- `GET /manifest`: Xem danh mục dữ liệu đầu vào.
- `GET /frames/{video_id}`: Lấy danh sách frame_id và timestamp_ms chuẩn của video.
- `GET /keyframe-image/{video_id}/{filename}`: Truy xuất ảnh Keyframe.
- `GET /runs/{run_id}/validate`: **(Quan trọng)** Quét toàn bộ lỗi hệ thống (P0, P1, P2) như duplicate mapping, sai PTS, thiếu file ảnh.

## 5. Quy tắc vận hành

1. **Video Gốc Là Sự Thật Cuối Cùng:** Hệ thống chỉ sử dụng PTS/Time_base từ video gốc, tuyệt đối không dùng proxy ID làm submission.
2. **Resumability:** Tất cả các WP (đặc biệt là WP01 và WP02) đều có khả năng bỏ qua (skip) các video đã được xử lý thành công. Nếu script bị crash giữa chừng, bạn chỉ việc chạy lại đúng lệnh đó.
3. **Data Contracts:** Mọi bảng Parquet sinh ra đều tuân thủ chặt chẽ Schema đã được định nghĩa cho AIC 2026.
