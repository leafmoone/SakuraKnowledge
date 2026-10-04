"""Small packaging guards; no model copies/index rebuilds."""
from pathlib import Path

import pytest

from tools.portable_pack import assemble, binding


def test_binding_hashes_actual_bytes_and_relative_path(tmp_path):
    p=tmp_path/'space file'
    p.write_bytes(b'abc')
    assert binding(p,tmp_path)=={'path':'space file','size':3,'sha256':'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'}
    with pytest.raises(ValueError):binding(p, tmp_path/'other')


def test_existing_manifest_refused_without_asset_replacement(tmp_path):
    # Manifest rejection occurs before reading huge source assets.
    repo=tmp_path/'repo'
    old=repo/'build/p4-dev-2048-1mib-3ee34e2-v1'
    old.mkdir(parents=True)
    (old/'manifest.json').write_text('{}')
    cfg=repo/'configs'
    cfg.mkdir()
    (cfg/'p4-full-semantic-v1.json').write_text('{}')
    output=tmp_path/'output'
    output.mkdir()
    (output/'manifest.json').write_text('preserve')
    with pytest.raises(FileExistsError):assemble(repo,output,Path('never-read'))
    assert (output/'manifest.json').read_text()=='preserve'
