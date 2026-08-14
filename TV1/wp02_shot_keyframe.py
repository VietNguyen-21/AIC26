import os
import sys
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import traceback

import av
import cv2
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# --- CORE FUNCTIONS ---
def phash(image: np.ndarray, hash_size: int = 8, highfreq_factor: int = 4) -> np.ndarray:
    img_size = hash_size * highfreq_factor
    resized = cv2.resize(image, (img_size, img_size), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY) if len(resized.shape) == 3 else resized
    dct = cv2.dct(np.float32(gray))
    dctlowfreq = dct[0:hash_size, 0:hash_size]
    med = np.median(dctlowfreq)
    return (dctlowfreq > med).flatten()


def hamming_distance(hash1: np.ndarray, hash2: np.ndarray) -> int:
    return np.count_nonzero(hash1 != hash2)


def compute_histogram(image: np.ndarray) -> np.ndarray:
    # Resize nhỏ lại để tính Histogram siêu tốc
    small = cv2.resize(image, (320, 240))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
    cv2.normalize(hist, hist, alpha=0, beta=1, norm_type=cv2.NORM_MINMAX)
    return hist


def compute_sharpness(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return cv2.Laplacian(gray, cv2.CV_64F).var()


# --- XỬ LÝ 1 VIDEO TỐI ƯU HÓA ---
def process_single_video(video_id: str, video_path: Path, run_dir: Path, preprocess_run_id: str, config: dict) -> dict:
    keyframes_dir = run_dir / "keyframes" / video_id
    thumbnails_dir = run_dir / "thumbnails" / video_id
    mappings_dir = run_dir / "mappings"
    shots_dir = run_dir / "shots"

    for d in [keyframes_dir, thumbnails_dir, mappings_dir, shots_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # --- THÔNG SỐ TỐI ƯU CHO TV2 & TV3 ---
    threshold = config.get("threshold", 0.65)
    min_gap_ms = config.get("min_gap_ms", 1500)  # Cooldown 1.5s giữa các keyframe
    max_gap_ms = config.get("max_gap_ms", 10000)  # Bắt buộc cắt 1 ảnh mỗi 10s
    dedup_threshold = config.get("dedup_threshold", 12)  # Lọc trùng lặp mạnh tay hơn (12 thay vì 5)
    target_eval_fps = 3.0  # Chỉ quét 3 khung hình/giây để tiết kiệm CPU

    frame_records, shot_records = [], []

    try:
        container = av.open(str(video_path))
        stream = container.streams.video[0]
        fps = float(stream.average_rate) if stream.average_rate else 30.0

        # Tự động tính frame_skip để chỉ quét 3 ảnh/giây
        frame_skip = max(1, int(fps / target_eval_fps))

        prev_hist = None
        prev_hash = None

        # OOM FIX: Chỉ lưu ĐÚNG 1 BỨC ẢNH tốt nhất trong RAM thay vì 1 list dài
        best_candidate = None
        last_extracted_ms = -min_gap_ms

        shot_count = 0
        current_shot_id = f"{video_id}_shot_{shot_count:04d}"
        shot_start_frame_id = 0
        shot_start_ms = 0

        temp_extracted = []
        frame_idx_in_stream = -1

        for frame in container.decode(video=0):
            frame_idx_in_stream += 1
            if frame_idx_in_stream % frame_skip != 0:
                continue

            pts = frame.pts
            if frame.time is not None:
                timestamp_ms = int(frame.time * 1000)
            elif pts is not None and stream.time_base:
                timestamp_ms = int(pts * stream.time_base * 1000)
            else:
                timestamp_ms = int((frame_idx_in_stream / fps) * 1000)

            frame_id = frame.index if hasattr(frame, 'index') else frame_idx_in_stream

            # Giải nén ảnh
            img = frame.to_ndarray(format='bgr24')
            hist = compute_histogram(img)
            sharpness = compute_sharpness(img)

            # --- TÌM SHOT BOUNDARY ---
            boundary_detected = False
            if prev_hist is not None:
                correlation = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if correlation < threshold:
                    boundary_detected = True

            gap_ms = timestamp_ms - last_extracted_ms

            # --- QUYẾT ĐỊNH CẮT ẢNH ---
            force_extract = False
            reason = ""

            if gap_ms >= max_gap_ms:
                force_extract = True
                reason = "max_gap"
            elif boundary_detected and gap_ms >= min_gap_ms:
                force_extract = True
                reason = "boundary_guard"

            if force_extract and best_candidate is not None:
                # Kiểm tra lọc trùng lặp (Dedup)
                is_dup = False
                if prev_hash is not None:
                    dist = hamming_distance(prev_hash, best_candidate["hash"])
                    if dist <= dedup_threshold:
                        is_dup = True

                if not is_dup:
                    temp_extracted.append((best_candidate, reason))
                    prev_hash = best_candidate["hash"]
                    last_extracted_ms = best_candidate["timestamp_ms"]

                # Lưu thông tin Shot
                if boundary_detected:
                    shot_records.append({
                        "video_id": video_id, "shot_id": current_shot_id,
                        "start_frame_id": shot_start_frame_id, "end_frame_id": frame_id,
                        "start_ms": shot_start_ms, "end_ms": timestamp_ms,
                        "duration_ms": timestamp_ms - shot_start_ms
                    })
                    shot_count += 1
                    current_shot_id = f"{video_id}_shot_{shot_count:04d}"
                    shot_start_frame_id, shot_start_ms = frame_id, timestamp_ms

                # Reset Best Candidate cho cảnh mới
                best_candidate = None

            # --- CẬP NHẬT BEST CANDIDATE TRONG CẢNH HIỆN TẠI ---
            if best_candidate is None or sharpness > best_candidate["sharpness"]:
                best_candidate = {
                    "frame_id": frame_id, "timestamp_ms": timestamp_ms, "pts": pts,
                    "sharpness": sharpness, "blur_score": 1.0 / max(sharpness, 1e-6),
                    "hash": phash(img), "img": img, "shot_id": current_shot_id
                }

            prev_hist = hist

        # Cuối video: Lấy nốt candidate còn sót lại
        if best_candidate is not None:
            temp_extracted.append((best_candidate, "end_of_video"))
            shot_records.append({
                "video_id": video_id, "shot_id": current_shot_id,
                "start_frame_id": shot_start_frame_id, "end_frame_id": best_candidate["frame_id"],
                "start_ms": shot_start_ms, "end_ms": best_candidate["timestamp_ms"],
                "duration_ms": best_candidate["timestamp_ms"] - shot_start_ms
            })

        container.close()

        # --- GHI RA Ổ CỨNG VÀ DATABASE ---
        utc_now = datetime.now(timezone.utc).isoformat()

        for keyframe_seq, (candidate, reason) in enumerate(temp_extracted):
            kf_rel_path = f"keyframes/{video_id}/{keyframe_seq}.jpg"
            thumb_rel_path = f"thumbnails/{video_id}/{keyframe_seq}.jpg"

            # Ghi ảnh
            cv2.imwrite(str(run_dir / kf_rel_path), candidate["img"], [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            thumb_img = cv2.resize(candidate["img"], (240, 180), interpolation=cv2.INTER_AREA)
            cv2.imwrite(str(run_dir / thumb_rel_path), thumb_img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])

            # Ghi Record
            frame_records.append({
                "schema_version": "1.0.0", "preprocess_run_id": preprocess_run_id,
                "video_id": video_id, "frame_id": int(candidate["frame_id"]),
                "keyframe_seq": int(keyframe_seq), "timestamp_ms": int(candidate["timestamp_ms"]),
                "pts": int(candidate["pts"]) if candidate["pts"] is not None else None,
                "shot_id": candidate["shot_id"], "keyframe_path": kf_rel_path,
                "thumbnail_path": thumb_rel_path, "selection_reason": reason,
                "sharpness_score": float(candidate["sharpness"]), "blur_score": float(candidate["blur_score"]),
                "created_at_utc": utc_now
            })

        if frame_records:
            pq.write_table(pa.Table.from_pandas(pd.DataFrame(frame_records)), mappings_dir / f"{video_id}.parquet")
        if shot_records:
            pq.write_table(pa.Table.from_pandas(pd.DataFrame(shot_records)), shots_dir / f"{video_id}.parquet")

        return {"video_id": video_id, "status": "success", "keyframes": len(frame_records)}

    except Exception as e:
        traceback.print_exc()
        return {"video_id": video_id, "status": "error", "error": str(e)}


# --- QUẢN LÝ ĐA LUỒNG (ORCHESTRATOR) ---
class ShotKeyframeExtractor:
    def __init__(self, raw_dir: Path, run_dir: Path, config: dict = None):
        self.raw_dir = Path(raw_dir)
        self.run_dir = Path(run_dir)
        self.config = config or {}
        self.preprocess_run_id = self.config.get("preprocess_run_id", "run_v1")
        # Giới hạn max_workers để tránh lỗi Out Of Memory (OOM)
        default_workers = min(4, max(1, os.cpu_count() - 1))
        self.max_workers = self.config.get("max_workers") or default_workers

        self.logger = logging.getLogger("WP02")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            ch = logging.StreamHandler(sys.stdout)
            ch.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            self.logger.addHandler(ch)

    def run(self):
        self.logger.info(f"Starting Multi-core Extraction (Max workers: {self.max_workers})")
        videos = [(p.stem, p) for p in self.raw_dir.rglob("*.mp4")]

        futures = []
        with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
            for video_id, v_path in videos:
                kf_dir = self.run_dir / "keyframes" / video_id
                if kf_dir.exists() and any(kf_dir.iterdir()):
                    self.logger.info(f"Skipping {video_id}, already processed.")
                    continue

                futures.append(executor.submit(
                    process_single_video, video_id, v_path, self.run_dir, self.preprocess_run_id, self.config
                ))

            for future in as_completed(futures):
                res = future.result()
                if res["status"] == "success":
                    self.logger.info(f"✅ {res['video_id']} - Trích xuất: {res['keyframes']} ảnh siêu nét.")
                else:
                    self.logger.error(f"❌ Lỗi {res['video_id']}: {res.get('error')}")

        # Merge mappings
        self.logger.info("Merging mappings into frames.parquet...")
        all_frames = [pd.read_parquet(p) for p in (self.run_dir / "mappings").glob("*.parquet")]
        if all_frames:
            merged_df = pd.concat(all_frames, ignore_index=True)
            pq.write_table(pa.Table.from_pandas(merged_df), self.run_dir / "frames.parquet")
            self.logger.info(f"🎉 Xong! Tổng cộng có {len(merged_df)} khung hình chất lượng cao.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw_dir", type=str, default="data/raw")
    parser.add_argument("--run_dir", type=str, default="data/runs/run_v1_batch1")
    # Phục hồi lại các tham số cũ để tương thích với lệnh của bạn:
    parser.add_argument("--preprocess_run_id", type=str, default="run_v1_batch1")
    parser.add_argument("--threshold", type=float, default=0.65)
    parser.add_argument("--max_gap_ms", type=int, default=10000)
    parser.add_argument("--max_workers", type=int, default=None)
    args = parser.parse_args()

    config = {
        "preprocess_run_id": args.preprocess_run_id,
        "threshold": args.threshold,
        "max_gap_ms": args.max_gap_ms,
        "max_workers": args.max_workers
    }

    extractor = ShotKeyframeExtractor(Path(args.raw_dir), Path(args.run_dir), config)
    extractor.run()