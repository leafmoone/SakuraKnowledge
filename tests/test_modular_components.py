import json

import pytest

from tools.modular_components import assemble
from tools.modular_validate import normalize


def test_assembly_does_not_consume_and_manifest_is_retained(tmp_path):
    core = tmp_path / 'core'
    core.mkdir()
    (core / 'sknow-config.json').write_text('{}')
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'manifest.json').write_text(json.dumps({'pack_id': 'moegirl'}))
    (source / 'knowledge.sqlite').write_bytes(b'readonly source')
    root = tmp_path / '中文 空格 install'
    assemble(core, None, [source], root)
    assert (source / 'knowledge.sqlite').read_bytes() == b'readonly source'
    assert (root / 'packs/moegirl/knowledge.sqlite').read_bytes() == b'readonly source'
    assert (root / 'packs/moegirl/manifest.json').is_file()
    with pytest.raises(FileExistsError):
        assemble(core, None, [source], root)


def test_failed_stage_does_not_publish_and_keeps_inputs(tmp_path):
    core = tmp_path / 'core'
    core.mkdir()
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'manifest.json').write_text('{bad')
    root = tmp_path / 'output'
    with pytest.raises(json.JSONDecodeError):
        assemble(core, None, [source], root)
    assert not root.exists()
    assert not root.with_name('output.assemble-stage').exists()
    assert (source / 'manifest.json').exists()


def test_business_normalization_does_not_hide_status_or_citations():
    one = {'status': 'ambiguous', 'source_packs': ['a'], 'citations': [{'source_id': 'real', 'evidence_id': 'proof'}]}
    two = {'status': 'found', 'citations': [{'source_id': 'real', 'evidence_id': 'proof'}]}
    assert normalize(one) != normalize(two)
    two['status'] = 'ambiguous'
    assert normalize(one) == normalize(two)
    two['citations'][0]['source_id'] = 'different'
    assert normalize(one) != normalize(two)
