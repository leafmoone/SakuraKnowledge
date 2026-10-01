"""Coverage audit source contract checks; no production snapshot access."""
import ast
from pathlib import Path

SOURCE = Path(__file__).parents[1] / 'tools/p4_corpus_audit.py'


def test_audit_is_readonly_and_does_not_promote_payload():
    text = SOURCE.read_text(encoding='utf-8')
    ast.parse(text)
    assert '?mode=ro&immutable=1' in text
    assert 'PRAGMA query_only=ON' in text
    assert "d.status IN ('source_backed','generated_from_evidence')" in text
    assert "v.status='source_backed'" in text
    assert 'e.conflicted=0' in text
    assert 'f.entry_id=e.id' in text
    assert 'json_extract' not in text
    assert "return 2 if missing else 0" in text
