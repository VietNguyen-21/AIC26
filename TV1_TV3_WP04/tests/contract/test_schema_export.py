import json
from pathlib import Path
from typer.testing import CliRunner

from aic2026.cli import SCHEMA_MODELS, app


def test_schema_export_contains_only_tv1_and_handoff_contracts(tmp_path: Path):
    result = CliRunner().invoke(app, ["export-schemas", "--output", str(tmp_path)])
    assert result.exit_code == 0, result.output
    expected = {f"{model.__name__}.schema.json" for model in SCHEMA_MODELS} | {"Settings.schema.json"}
    actual = {path.name for path in tmp_path.glob("*.json")}
    assert actual == expected
    for path in tmp_path.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload.get("type") == "object" or "$defs" in payload
    forbidden = {"VisualModelManifest.schema.json", "OCRRecord.schema.json", "PredictionRecord.schema.json"}
    assert not forbidden.intersection(actual)
