import pytest

from wp04.adapters import AdapterUnavailableError
from wp04.contracts import FrameRecord
from wp04.runtime_adapters import build_ocr_adapter


def test_command_ocr_adapter_reports_missing_local_command_before_inference():
    adapter = build_ocr_adapter(command_env="MISSING_WP04_OCR_COMMAND")
    frame = FrameRecord("tv1", "v", 42, 1, 1400, "keyframes/42.jpg", "sha")
    with pytest.raises(AdapterUnavailableError, match="MISSING_WP04_OCR_COMMAND"):
        adapter.detect(frame)
