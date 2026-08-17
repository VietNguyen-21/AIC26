from aic2026.batch_manifest import _column_index

def test_column_index():
    assert _column_index('A1')==0 and _column_index('AA9')==26
