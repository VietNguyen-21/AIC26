import os
import sys
import math
import argparse
import subprocess
import shutil
import sqlite3
import yaml
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

def run_batch(batch_idx, batch_videos, run_id_prefix, config_path):
    # Tạo thư mục ảo (chứa hardlink của video)
    tmp_dir = Path(f"data/tmp_batch_{batch_idx}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    for v in batch_videos:
        target = tmp_dir / v.name
        # Hardlink không làm tốn dung lượng ổ cứng, chỉ tạo 1 "lối tắt"
        if not target.exists():
            os.link(str(v), str(target))
    
    run_id = f"{run_id_prefix}_{batch_idx}"
    
    # Sử dụng đúng môi trường Python đang chạy script này
    cmd = [
        sys.executable, "-m", "aic2026.cli", "preprocess", 
        "--input", str(tmp_dir), 
        "--run-id", run_id, 
        "--config", config_path
    ]
    
    print(f"\n[Luồng {batch_idx}] Bắt đầu xử lý {len(batch_videos)} video với run-id: {run_id}")
    try:
        subprocess.run(cmd, check=True)
        print(f"\n[Luồng {batch_idx}] ✔ HOÀN THÀNH!")
        return True
    except subprocess.CalledProcessError:
        print(f"\n[Luồng {batch_idx}] ❌ LỖI trong quá trình xử lý!")
        return False
    except Exception as e:
        print(f"\n[Luồng {batch_idx}] ❌ LỖI HỆ THỐNG: {e}")
        return False

def merge_runs(base_run_id, workers, config_path):
    print(f"\n[GOM DỮ LIỆU] Đang tiến hành gom kết quả từ {workers} luồng về một mối ({base_run_id})...")
    
    # Đọc cấu hình để biết runs_root nằm ở đâu
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
            runs_root = Path(config.get("paths", {}).get("runs_root", "data/runs"))
    except:
        runs_root = Path("data/runs")
        
    target_dir = runs_root / base_run_id
    target_dir.mkdir(parents=True, exist_ok=True)
    
    target_db_path = target_dir / "registry" / "run_registry.sqlite3"
    target_db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Copy DB đầu tiên sang làm gốc
    first_db = runs_root / f"{base_run_id}_1" / "registry" / "run_registry.sqlite3"
    if first_db.exists():
        shutil.copy2(first_db, target_db_path)
    
    with sqlite3.connect(target_db_path) as conn:
        cursor = conn.cursor()
        
        for i in range(1, workers + 1):
            source_dir = runs_root / f"{base_run_id}_{i}"
            if not source_dir.exists():
                continue
                
            # 1. Gom Database SQLite
            if i > 1:
                db_path = source_dir / "registry" / "run_registry.sqlite3"
                if db_path.exists():
                    cursor.execute(f"ATTACH DATABASE '{db_path}' AS db_{i}")
                    cursor.execute(f"""
                        INSERT OR IGNORE INTO module_status 
                        SELECT '{base_run_id}', video_id, module, fingerprint, status, details, attempt_count, started_at, finished_at, updated_at 
                        FROM db_{i}.module_status
                    """)
                    cursor.execute(f"DETACH DATABASE db_{i}")
            
            # 2. Gom File & Thư mục vật lý
            for item in source_dir.glob("*"):
                if item.name == "registry":
                    # Copy thư mục cache trong registry
                    cache_src = item / "cache"
                    cache_dst = target_dir / "registry" / "cache"
                    if cache_src.exists():
                        cache_dst.mkdir(parents=True, exist_ok=True)
                        for video_cache in cache_src.glob("*"):
                            if video_cache.is_dir():
                                shutil.copytree(video_cache, cache_dst / video_cache.name, dirs_exist_ok=True)
                    continue
                
                target_item = target_dir / item.name
                if item.is_dir():
                    target_item.mkdir(exist_ok=True)
                    for sub_item in item.glob("*"):
                        if sub_item.is_dir():
                            shutil.copytree(sub_item, target_item / sub_item.name, dirs_exist_ok=True)
                        else:
                            if sub_item.suffix == ".jsonl":
                                with open(target_item / sub_item.name, "a", encoding="utf-8") as out_f:
                                    with open(sub_item, "r", encoding="utf-8") as in_f:
                                        out_f.write(in_f.read())
                            elif sub_item.suffix != ".parquet":  # Bỏ qua parquet vì không nối text được
                                shutil.copy2(sub_item, target_item / sub_item.name)
                else:
                    if item.suffix == ".jsonl":
                        with open(target_item, "a", encoding="utf-8") as out_f:
                            with open(item, "r", encoding="utf-8") as in_f:
                                out_f.write(in_f.read())
            
            # Xóa thư mục tạm của luồng này sau khi gom xong cho sạch máy
            try:
                shutil.rmtree(source_dir)
            except:
                pass
            
            # Xóa thư mục hardlink ảo
            try:
                shutil.rmtree(Path(f"data/tmp_batch_{i}"))
            except:
                pass

    print(f"[GOM DỮ LIỆU] ✔ Tuyệt vời! Đã gom tất cả về thư mục duy nhất: {target_dir}")

def main():
    parser = argparse.ArgumentParser(description="Chạy aic preprocess song song")
    parser.add_argument("--input", required=True, help="Thư mục chứa video gốc (vd: D:/train_aic/AIC26/raw_video)")
    parser.add_argument("--run-id", required=True, help="Tên tiền tố run-id (vd: chay_chinh_thuc)")
    parser.add_argument("--config", default="configs/external_video_smoke.yaml", help="Đường dẫn file cấu hình")
    parser.add_argument("--workers", type=int, default=4, help="Số luồng chạy song song (tùy thuộc vào CPU/RAM của bạn)")
    args = parser.parse_args()

    source_dir = Path(args.input)
    if not source_dir.exists():
        print(f"Lỗi: Không tìm thấy thư mục {source_dir}")
        return

    # Lọc danh sách video
    videos = sorted([p for p in source_dir.rglob("*") if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".avi", ".mov", ".webm"}])
    
    if not videos:
        print(f"Lỗi: Không tìm thấy video nào trong {source_dir}")
        return

    print(f"Tìm thấy tổng cộng {len(videos)} video. Bắt đầu chia đều cho {args.workers} luồng...")

    # Chia video thành các nhóm nhỏ bằng nhau
    batch_size = math.ceil(len(videos) / args.workers)
    batches = [videos[i:i + batch_size] for i in range(0, len(videos), batch_size)]

    # Chạy đa luồng
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = []
        for idx, batch in enumerate(batches):
            if batch:
                futures.append(executor.submit(run_batch, idx + 1, batch, args.run_id, args.config))
        
        for future in as_completed(futures):
            future.result() 

    print("\n🎉 HOÀN THÀNH XỬ LÝ SONG SONG!")
    merge_runs(args.run_id, args.workers, args.config)

if __name__ == "__main__":
    main()
