from wp04.contracts import AudioRecord, FrameRecord
from wp04.adapters import OCRRawDetection
from wp04.pipeline import Pipeline, FakeAdapter, WP04Pipeline
from wp04.contracts import WP04RunIdentity
from wp04.storage import ArtifactStore

def test_pipeline_isolates_one_adapter_failure():
    result = Pipeline({"ocr": FakeAdapter(error="load failed"), "object": FakeAdapter()}).run(["L01_V001"], "fp")
    assert result[0].state == "failed"
    assert result[1].state == "ready"


class FakeOCR:
    def detect(self, frame: FrameRecord):
        return []


class FailingOCR:
    def detect(self, frame: FrameRecord):
        raise RuntimeError("model checkpoint missing")


class FakeASR:
    def transcribe(self, audio: AudioRecord):
        return []


class FakeObjects:
    def detect(self, frame: FrameRecord):
        return []


def test_asr_without_declared_audio_is_no_audio_and_does_not_stop_ocr():
    frame = FrameRecord("tv1", "L01_V001", 42, 1, 1400)
    audio = AudioRecord("tv1", "L01_V001", None, None, False, None)
    result = WP04Pipeline(FakeOCR(), FakeASR(), FakeObjects()).run([frame], {frame.video_id: audio}, "fp")
    assert result.status_for("L01_V001", "asr").state == "no_audio"
    assert result.status_for("L01_V001", "ocr").state == "ready"


def test_failed_ocr_is_visible_while_object_pipeline_completes():
    frame = FrameRecord("tv1", "L01_V001", 42, 1, 1400)
    audio = AudioRecord("tv1", "L01_V001", None, None, False, None)
    result = WP04Pipeline(FailingOCR(), FakeASR(), FakeObjects()).run([frame], {frame.video_id: audio}, "fp")
    assert result.status_for("L01_V001", "ocr").state == "failed"
    assert result.status_for("L01_V001", "object").state == "ready"


def test_expected_audio_missing_is_failed_not_no_audio():
    frame = FrameRecord("tv1", "L01_V001", 42, 1, 1400)
    result = WP04Pipeline(FakeOCR(), FakeASR(), FakeObjects()).run([frame], {}, "fp")
    assert result.status_for("L01_V001", "asr").state == "failed"


class DetectingOCR:
    model_name = "deepsolo-parseq-vn"
    model_version = "v1"

    def detect(self, frame: FrameRecord):
        return [OCRRawDetection("BÁNH MÌ", (0.1, 0.2, 0.3, 0.4), 0.9)]


def test_run_and_store_persists_normalized_ocr_before_ready_status(tmp_path):
    frame = FrameRecord("tv1", "L01_V001", 42, 1, 1400)
    audio = AudioRecord("tv1", "L01_V001", None, None, False, None)
    store = ArtifactStore(tmp_path, WP04RunIdentity("tv1", "wp04", "inputs", "config"))
    result = WP04Pipeline(DetectingOCR(), FakeASR(), FakeObjects()).run_and_store([frame], {frame.video_id: audio}, "fp", store)
    assert result.status_for("L01_V001", "ocr").state == "ready"
    row = store.read_records("ocr", "L01_V001")[0]
    assert row["normalized_text"] == "bánh mì"
    assert row["evidence_id"] == "ocr:L01_V001:42:0"


class WrongShapeOCR:
    def detect(self, frame: FrameRecord):
        return [{"text": "not a raw detection"}]


def test_wrong_raw_adapter_output_is_failed_not_ready(tmp_path):
    frame = FrameRecord("tv1", "L01_V001", 42, 1, 1400)
    audio = AudioRecord("tv1", "L01_V001", None, None, False, None)
    store = ArtifactStore(tmp_path, WP04RunIdentity("tv1", "wp04", "inputs", "config"))
    result = WP04Pipeline(WrongShapeOCR(), FakeASR(), FakeObjects()).run_and_store([frame], {frame.video_id: audio}, "fp", store)
    assert result.status_for("L01_V001", "ocr").state == "failed"
