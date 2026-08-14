from tv4.contracts import SearchCandidate
from tv4.wp10_fusion import fuse_kis, reciprocal_rank_fusion


def _cand(video_id, frame_id, ts, source, rank, score=None):
    return SearchCandidate(
        query_id="q1", video_id=video_id, frame_id=frame_id, timestamp_ms=ts,
        source=source, rank=rank, score=score,
    )


def test_agreeing_branches_outrank_single_branch():
    visual = [_cand("L01_V001", 100, 5000, "visual", 1), _cand("L02_V002", 50, 1000, "visual", 2)]
    ocr = [_cand("L01_V001", 100, 5000, "ocr", 1)]
    fused = fuse_kis({"visual": visual, "ocr": ocr})
    assert fused[0].video_id == "L01_V001"
    assert fused[0].rank == 1
    assert "ocr" in fused[0].provenance_sources and "visual" in fused[0].provenance_sources


def test_empty_branch_does_not_crash():
    fused = fuse_kis({"visual": [], "ocr": [], "asr": []})
    assert fused == []


def test_dedup_window_merges_near_duplicate_frames():
    visual = [_cand("L01_V001", 100, 5000, "visual", 1), _cand("L01_V001", 101, 5050, "visual", 2)]
    fused = reciprocal_rank_fusion({"visual": visual}, dedup_window_ms=1000)
    assert len(fused) == 1


def test_diversity_caps_per_video():
    visual = [_cand("L01_V001", i, i * 5000, "visual", i + 1) for i in range(10)]
    fused = fuse_kis({"visual": visual}, top_k=100)
    same_video = [c for c in fused if c.video_id == "L01_V001"]
    assert len(same_video) <= 5
