from __future__ import annotations

import pytest
import yaml

from wp03.config import ModelRuntimeSpec, load_build_config
from wp03.contracts import ContractError
from wp03.worker_protocol import compatibility_fingerprint


def _model() -> dict[str, object]:
    return {
        "model_id": "vendor/model",
        "revision": "a" * 40,
        "tokenizer_revision": "b" * 40,
        "image_preprocess": {"image_size": 224},
        "text_preprocess": {"unicode_normalization": "NFC"},
        "query_template": "{query}",
        "expected_dimension": 768,
        "dtype": "bfloat16",
        "fallback_dtype": "float16",
        "batch_size": 4,
        "timeout_seconds": 900,
    }


def test_build_config_rejects_model_without_tokenizer_revision() -> None:
    model = _model()
    del model["tokenizer_revision"]

    with pytest.raises(ContractError, match="tokenizer_revision"):
        load_build_config({"models": {"bge_vl": model}})


def test_semantic_model_change_changes_compatibility_fingerprint() -> None:
    first = ModelRuntimeSpec.from_mapping("bge_vl", _model())
    changed = _model()
    changed["query_template"] = "query: {query}"
    second = ModelRuntimeSpec.from_mapping("bge_vl", changed)

    assert compatibility_fingerprint(spec=first) != compatibility_fingerprint(spec=second)


def test_build_config_exposes_retrieval_policy() -> None:
    config = load_build_config(
        {
            "rrf_k": 10,
            "dedup_window_ms": 750,
            "models": {"bge_vl": _model()},
        }
    )

    assert config.rrf_k == 10
    assert config.dedup_window_ms == 750


@pytest.mark.parametrize("name", ["smoke.yaml", "full.yaml"])
def test_shipped_configs_define_the_four_advanced_models(name: str) -> None:
    config_path = __import__("pathlib").Path(__file__).parents[1] / "configs" / name
    config = load_build_config(yaml.safe_load(config_path.read_text(encoding="utf-8")))

    assert tuple(config.models) == ("beit3", "bge_vl", "metaclip2", "perception")
