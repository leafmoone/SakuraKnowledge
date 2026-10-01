"""Audit PASS requires exact trusted census and post-read integrity, not four families."""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest
import test_p4_corpus as fixtures

p4 = fixtures.p4
config = fixtures.config
snapshot = fixtures.snapshot
project_root = fixtures.project_root


@pytest.fixture
def audit_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "p4_corpus", p4)
    spec = importlib.util.spec_from_file_location(
        "p4_corpus_audit", Path(__file__).parents[1] / "tools/p4_corpus_audit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_pass_without_moegirl_local_tag(snapshot, config, audit_module):
    before = p4.sha256_file(snapshot)
    report = audit_module.audit(snapshot, config, "config-digest")
    assert report["coverage_gate"] == "PASS"
    assert report["eligible_total"] == 40
    assert report["trusted_text_census"] == {name: 10 for name in config["strata"]}
    assert set(report["semantic_ineligible"]) == {"moegirl", "local_tag"}
    assert report["snapshot_sha256_unchanged"] and report["sidecars_unchanged"]
    assert report["semantic_execution"] == "NOT_RUN"
    assert p4.sha256_file(snapshot) == before


@pytest.mark.parametrize("mutation,error", [
    ("DELETE FROM search_fts WHERE document_id=1", "census mismatch"),
    ("UPDATE build_meta SET value='true'", "index_episodes"),
    ("UPDATE entries SET namespace='unknown' WHERE id=1", "unexpected eligible stratum"),
])
def test_audit_rejects_census_policy_and_extra_stratum(snapshot, config, audit_module,
                                                     mutation, error):
    with sqlite3.connect(snapshot) as conn:
        conn.execute(mutation)
    config["snapshot"]["sha256"] = p4.sha256_file(snapshot)
    config["snapshot"]["size"] = snapshot.stat().st_size
    with pytest.raises(ValueError, match=error):
        audit_module.audit(snapshot, config, "digest")


def test_audit_sha_failure(snapshot, config, audit_module):
    config["snapshot"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        audit_module.audit(snapshot, config, "digest")


def test_audit_no_pass_on_sidecar_change(snapshot, config, audit_module, monkeypatch):
    original = audit_module.verify_census
    def changed(counts, configuration):
        original(counts, configuration)
        Path(str(snapshot) + "-shm").write_bytes(b"changed")
    monkeypatch.setattr(audit_module, "verify_census", changed)
    with pytest.raises(ValueError, match="changed during read"):
        audit_module.audit(snapshot, config, "digest")


def test_audit_cli_exit_zero_and_one_not_missing_family_exit_two(
        snapshot, config, audit_module, tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    args = ["--config", str(path), "--snapshot", str(snapshot)]
    assert audit_module.main(args) == 0
    assert json.loads(capsys.readouterr().out)["coverage_gate"] == "PASS"
    config["snapshot"]["sha256"] = "0" * 64
    path.write_text(json.dumps(config), encoding="utf-8")
    assert audit_module.main(args) == 1
    assert json.loads(capsys.readouterr().out)["coverage_gate"] == "FAIL"
