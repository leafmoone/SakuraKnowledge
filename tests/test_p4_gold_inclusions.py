"""Frozen-label inclusion mapping, no database or model execution."""
from pathlib import Path

import pytest

from tools.p4_gold_inclusions import inclusions


def test_frozen_mapping():
    raw = (Path(__file__).parents[1] / 'reports/P4/retrieval-gold.json').read_bytes()
    items = inclusions(raw)
    assert len(items) == 50
    assert len({x['document_id'] for x in items}) == 50
    assert all(x['reason'] and x['entry_key'] for x in items)
    assert [x['document_id'] for x in items] == sorted(x['document_id'] for x in items)
    assert items == inclusions(raw)
    with pytest.raises(ValueError, match='SHA mismatch'):
        inclusions(raw + b' ')
