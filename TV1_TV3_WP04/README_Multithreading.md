# 🚀 HƯỚNG DẪN SỬ DỤNG CHẠY ĐA LUỒNG (MULTITHREADING)

Hệ thống xử lý video của AIC rất nặng. Nếu chạy tuần tự từng video một, bạn sẽ tốn rất nhiều thời gian. Vì vậy, tôi đã tạo ra công cụ **`run_parallel.py`** để giúp bạn "phân thân" máy tính, xử lý nhiều video cùng lúc.

---

## 1. CÂU LỆNH CƠ BẢN
Để bắt đầu chạy, bạn hãy mở Terminal (PowerShell/Command Prompt) và gõ câu lệnh theo mẫu sau:

```powershell
python run_parallel.py --input "Đường_dẫn_chứa_video" --run-id "Tên_đợt_chạy" --config "File_cấu_hình.yaml" --workers Số_luồng
```

### Ví dụ thực tế:
```powershell
python run_parallel.py --input "D:\train_aic\AIC26\raw_video" --run-id "chay_nhanh_video" --config "configs/external_video_smoke.yaml" --workers 4
```

---

## 2. GIẢI THÍCH CÁC THÔNG SỐ (THẦN CHÚ)

* `--input`: Nơi chứa thư mục video gốc của bạn (vd: `D:\train_aic\AIC26\raw_video`). Script này đủ thông minh để tự động mò vào các thư mục con bên trong để gom đủ 60 video.
* `--run-id`: Đặt tên cho lần chạy này (vd: `chay_lan_1`). Kết quả sau khi chạy xong sẽ được lưu gọn gàng vào thư mục `data/runs/chay_lan_1`.
* `--config`: Đường dẫn tới file cấu hình mà bạn muốn dùng.
* `--workers`: **Quan trọng nhất!** Đây là số lượng luồng (số video chạy cùng lúc).

---

## 3. BÍ QUYẾT CHỌN SỐ LUỒNG (`--workers`)
Đừng bao giờ tham lam đặt số luồng quá cao, vì nếu máy tính bị quá tải (tràn RAM / VRAM), hệ thống sẽ bị treo hoặc văng lỗi sập nguồn.

**🧠 Trải nghiệm thực tế để chọn số:**
- **Nếu chạy bằng CPU (Dùng `external_video_smoke.yaml` và không cài AI):** 
  - Bạn có thể đặt `--workers 4` đến `--workers 10`. 
  - *Mẹo:* Bật Task Manager lên, nếu thấy CPU lên 100% thì đó là giới hạn tối đa, không nên tăng thêm.
- **Nếu chạy bằng GPU (Dùng `competition.yaml` + có cài AI nặng):** 
  - GPU (Card rời) có giới hạn bộ nhớ (VRAM) rất eo hẹp. 
  - Mỗi luồng tải mô hình AI có thể ngốn từ 2GB - 4GB VRAM.
  - Card 8GB: Chỉ nên để `--workers 1` hoặc `--workers 2`.
  - Card 12GB: Có thể để `--workers 3`.
  - Card 24GB (RTX 3090/4090): Có thể để `--workers 6` đến `8`.

---

## 4. QUÁ TRÌNH "PHÂN THÂN" VÀ "HỢP THỂ" HOẠT ĐỘNG THẾ NÀO?
1. **Chia nhỏ (Phân thân):** Khi bạn yêu cầu 4 luồng xử lý 60 video, script sẽ tự động chia 60 video ra làm 4 nhóm (mỗi nhóm 15 video) và giao cho 4 tiến trình (worker) chạy song song độc lập.
2. **Tiết kiệm ổ cứng:** Thay vì copy video ra làm nhiều bản gây tốn ổ cứng, script sử dụng kỹ thuật `Hardlink` cực kỳ thông minh của Windows để tạo đường dẫn ảo. 0 byte bị lãng phí!
3. **Gom dữ liệu (Hợp thể):** Sau khi cả 4 luồng chạy xong, script sẽ tự động gộp tất cả ảnh Keyframe, file cơ sở dữ liệu (`run_registry.sqlite3`), và `manifest.jsonl` từ 4 luồng về lại chung một chỗ (thư mục `--run-id` của bạn). Bạn chỉ việc lấy kết quả cuối cùng ra dùng, không cần làm gì thêm!
