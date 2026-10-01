"""Synthetic-only trusted-text census and exact quota tests."""
import hashlib
import importlib.util
import json
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from sakura_knowledge.storage import SCHEMA

SPEC = importlib.util.spec_from_file_location(
    "p4_corpus", Path(__file__).resolve().parents[1] / "tools/p4_corpus.py")
p4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p4)


@pytest.fixture(autouse=True)
def project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(p4, "ROOT", tmp_path)


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "synthetic.sqlite"
    config, _ = p4.load_config()
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO build_meta VALUES('index_episodes','false')")
        for sid in ("bangumi", "moegirl", "danbooru", "tag_wiki"):
            conn.execute("INSERT INTO sources VALUES(?,?)", (sid, json.dumps({"provider": sid})))
        for did in range(1, 41):
            spec = list(config["strata"].values())[(did - 1) // 10]
            sid = spec["source_family"]
            conn.execute("INSERT INTO entries(id,kind,namespace,value) VALUES(?,?,?,?)",
                         (did, spec["kind"], spec["namespace"], str(did)))
            for _ in range(2):
                conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                             "VALUES(?,?,?,'source_backed','{}')", (did, sid, f"identity:{did}"))
            conn.execute("INSERT INTO documents(id,entry_id,title,original,search_text,language,"
                         "status,source_id,evidence_id,payload) VALUES(?,?,?,?,?,NULL,?,?,?,'{}')",
                         (did, did, f"Title {did}", "中文", "中文",
                          "generated_from_evidence" if did % 2 else "source_backed", sid, f"doc:{did}"))
            conn.execute("INSERT INTO search_fts(text,document_id,entry_id) VALUES('中文',?,?)",
                         (did, did))
    return path


def opened(path):
    return p4.verified_snapshot(path, p4.sha256_file(path), path.stat().st_size)


@pytest.fixture
def config(snapshot):
    config, _ = p4.load_config()
    for spec in config["strata"].values():
        spec.update(eligible_count=10, pilot_quota=5)
    config.update(eligible_total=40, pilot_size=20)
    config["snapshot"] = {"path": str(snapshot), "sha256": p4.sha256_file(snapshot),
                          "size": snapshot.stat().st_size}
    return config


def test_frozen_configuration():
    config, digest = p4.load_config()
    assert config["eligible_total"] == 1295638
    assert [s["eligible_count"] for s in config["strata"].values()] == [690068, 221960, 102338, 281272]
    assert [s["pilot_quota"] for s in config["strata"].values()] == [26630, 8566, 3949, 10855]
    assert config["pilot_size"] == 50000 and config["seed"] == "sakura-p4-trusted-text-v1-2026"
    assert digest == p4.sha256_file(p4.DEFAULT_CONFIG)
    assert set(config["semantic_ineligible"]) == {"moegirl", "local_tag"}


def test_trust_membership_and_dedup(snapshot):
    with sqlite3.connect(snapshot) as conn:
        conn.execute("UPDATE entries SET conflicted=1 WHERE id=1")
        conn.execute("UPDATE documents SET status='unverified_draft' WHERE id=2")
        conn.execute("UPDATE entry_evidence SET status='generated_from_evidence' WHERE entry_id=3")
        conn.execute("UPDATE search_fts SET entry_id=6 WHERE document_id=4")
        conn.execute("UPDATE entries SET kind='episode' WHERE id=5")
        conn.execute("DELETE FROM search_fts WHERE document_id=6")
        conn.execute("INSERT INTO search_fts(text,document_id,entry_id) VALUES('duplicate',7,7)")
    before = p4.sha256_file(snapshot)
    with opened(snapshot) as (conn, _):
        docs = list(p4.eligible(conn, p4.source_metadata(conn)))
        assert {d["document_id"] for d in docs} == set(range(7, 41))
        assert len(docs) == 34
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM documents")
    assert p4.sha256_file(snapshot) == before


def test_exact_deterministic_selection_and_same_stratum_replacement(snapshot, config):
    with opened(snapshot) as (conn, _):
        sources = p4.source_metadata(conn)
        a = p4.select(conn, sources, config)
        assert a == p4.select(conn, sources, config)
        ids, _reasons, audit = a
        assert len(ids) == len(set(ids)) == 20
        assert audit["eligible_count"] == 40
        docs = [p4.fetch(conn, did, sources) for did in range(1, 41)]
        scores = {d["document_id"]: int(hashlib.sha256(
            f"{config['seed']}:{d['document_id']}".encode()).hexdigest(), 16) for d in docs}
        for name in config["strata"]:
            members = [d["document_id"] for d in docs if p4.stratum(d, config) == name]
            assert set(ids).intersection(members) == set(sorted(members, key=scores.get)[:5])
        assert ids == sorted(ids, key=scores.get)
        absent = next(d for d in docs if d["document_id"] not in ids)
        did, name = absent["document_id"], p4.stratum(absent, config)
        mandatory = {did: {"document_id": did, "entry_key": absent["entry_key"],
                           "role": "hard_negative", "reason": "frozen contrast"}}
        chosen, why, receipt = p4.select(conn, sources, config, mandatory)
        victim = max((i for i in ids if p4.stratum(p4.fetch(conn, i, sources), config) == name),
                     key=scores.get)
        assert set(chosen) == (set(ids) - {victim}) | {did}
        assert "mandatory:hard_negative" in why[did] and "frozen contrast" in why[did]
        assert receipt["mandatory_replacements"] == [{"stratum": name,
            "included_document_id": did, "removed_document_id": victim,
            "role": "hard_negative", "reason": "frozen contrast"}]
        mandatory[did]["entry_key"] = {}
        with pytest.raises(ValueError, match="key mismatch"):
            p4.select(conn, sources, config, mandatory)
        with pytest.raises(ValueError, match="not eligible"):
            p4.select(conn, sources, config, {999: {}})


def test_mandatory_overflow_and_already_selected(snapshot, config):
    with opened(snapshot) as (conn, _):
        sources = p4.source_metadata(conn)
        ids, _, _ = p4.select(conn, sources, config)
        def required(i):
            return {"document_id": i, "entry_key": p4.fetch(conn, i, sources)["entry_key"],
                    "role": "gold_target", "reason": "required target"}
        selected, _, receipt = p4.select(conn, sources, config, {ids[0]: required(ids[0])})
        assert selected == ids and receipt["mandatory_replacements"] == []
        with pytest.raises(ValueError, match="exceed quota"):
            p4.select(conn, sources, config, {i: required(i) for i in range(1, 7)})


@pytest.mark.parametrize("mutation,error", [
    ("DELETE FROM search_fts WHERE document_id=1", "census mismatch"),
    ("UPDATE entries SET namespace='unexpected' WHERE id=1", "unexpected eligible stratum"),
    ("UPDATE build_meta SET value='true'", "index_episodes"),
    ("DELETE FROM build_meta", "index_episodes"),
])
def test_census_and_policy_fail_closed(snapshot, config, mutation, error):
    with sqlite3.connect(snapshot) as conn:
        conn.execute(mutation)
    with opened(snapshot) as (conn, _), pytest.raises(ValueError, match=error):
        p4.select(conn, p4.source_metadata(conn), config)


def test_snapshot_verification_and_sidecars(snapshot):
    digest, size = p4.sha256_file(snapshot), snapshot.stat().st_size
    with pytest.raises(ValueError, match="size mismatch"), p4.verified_snapshot(snapshot, digest, size+1):
        pass
    with pytest.raises(ValueError, match="SHA256 mismatch"), p4.verified_snapshot(snapshot, "0"*64, size):
        pass
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(snapshot) + suffix)
        sidecar.write_bytes(b"not empty")
        with pytest.raises(ValueError, match="nonempty"), opened(snapshot):
            pass
        assert sidecar.read_bytes() == b"not empty"
        sidecar.unlink()
    sidecar = Path(str(snapshot) + "-shm")
    sidecar.write_bytes(b"before")
    with pytest.raises(ValueError, match="changed during read"), opened(snapshot):
        sidecar.write_bytes(b"after!")


def test_post_read_sha_detects_same_size_mtime_mutation(snapshot):
    import os
    stat = snapshot.stat()
    with pytest.raises(ValueError, match="changed during read"), opened(snapshot):
        with snapshot.open("r+b") as stream:
            stream.seek(-1, 2)
            byte = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes([byte[0] ^ 1]))
        os.utime(snapshot, ns=(stat.st_atime_ns, stat.st_mtime_ns))


def test_export_cli_roundtrip(snapshot, config, tmp_path, capsys):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    mandatory_path = tmp_path / 'mandatory.json'
    mandatory_path.write_text('[]', encoding='utf-8')
    corpus, manifest = p4.ROOT / "build/p4/pilot.jsonl", p4.ROOT / "reports/P4/manifest.json"
    before = p4.sha256_file(snapshot)
    args = ["--snapshot", str(snapshot), "--sha256", before,
            "--size", str(snapshot.stat().st_size), "export", "--config", str(config_path),
            "--corpus", str(corpus), "--manifest", str(manifest),
            '--mandatory', str(mandatory_path)]
    p4.main(args)
    summary = json.loads(capsys.readouterr().out)
    report = json.loads(manifest.read_bytes())
    docs = [json.loads(line) for line in corpus.read_bytes().splitlines()]
    assert len(docs) == len({d["document_id"] for d in docs}) == 20
    assert report["corpus_sha256"] == summary["corpus_sha256"] == p4.sha256_file(corpus)
    assert report["selected_census"] == Counter(p4.stratum(d, config) for d in docs)
    assert set(report["selected_census"].values()) == {5}
    assert report["config_sha256"] == p4.sha256_file(config_path)
    assert report["base_snapshot"]["sha256"] == before == p4.sha256_file(snapshot)
    with opened(snapshot) as (conn, _):
        sources = p4.source_metadata(conn)
        ids, reasons, audit = p4.select(conn, sources, config)
        assert [d["document_id"] for d in docs] == ids
        assert report["eligible_sha256"] == audit["eligible_sha256"]
        for doc in docs:
            assert doc == {**p4.fetch(conn, doc["document_id"], sources),
                           "selection_reasons": reasons[doc["document_id"]]}
    frozen = corpus.read_bytes(), manifest.read_bytes()
    with pytest.raises(FileExistsError):
        p4.main(args)
    assert frozen == (corpus.read_bytes(), manifest.read_bytes())


def test_mismatched_fts_text_excluded(snapshot):
    with sqlite3.connect(snapshot) as conn:
        conn.execute("UPDATE search_fts SET text='stale' WHERE document_id=1")
    with opened(snapshot) as (conn, _):
        docs = list(p4.eligible(conn, p4.source_metadata(conn)))
    assert {d['document_id'] for d in docs} == set(range(2, 41))


def test_export_integrity_failure_leaves_no_manifest(snapshot, config, tmp_path, monkeypatch):
    cp = tmp_path / 'config.json'
    cp.write_text(json.dumps(config), encoding='utf-8')
    mp = tmp_path / 'mandatory.json'
    mp.write_text('[]', encoding='utf-8')
    corpus = p4.ROOT / 'build/p4/pilot.jsonl'
    manifest = p4.ROOT / 'reports/P4/manifest.json'
    original = p4.export

    def changed(*args, **kwargs):
        report = original(*args, **kwargs)
        assert corpus.exists() and not manifest.exists()
        Path(str(snapshot) + '-shm').write_bytes(b'changed')
        return report

    monkeypatch.setattr(p4, 'export', changed)
    with pytest.raises(ValueError, match='changed during read'):
        p4.main(['--snapshot', str(snapshot), '--sha256', p4.sha256_file(snapshot),
                 '--size', str(snapshot.stat().st_size), 'export', '--config', str(cp),
                 '--corpus', str(corpus), '--manifest', str(manifest), '--mandatory', str(mp)])
    assert corpus.exists() and not manifest.exists()


def test_inspect_cli(snapshot, capsys):
    p4.main(["--snapshot", str(snapshot), "--sha256", p4.sha256_file(snapshot),
             "--size", str(snapshot.stat().st_size), "inspect", "--document-id", "1",
             "--excerpt-chars", "1"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["document_id"] == 1 and doc["original"] == "中"
    assert doc["original_characters"] == 2
    assert not list((p4.ROOT / "build/p4").iterdir())


def test_mandatory_input(tmp_path):
    path = tmp_path / "frozen.json"
    item = {"document_id": 2, "entry_key": {"kind": "page", "namespace": "x", "value": "2"},
            "role": "gold_target", "reason": "source anchored"}
    path.write_text(json.dumps([item]), encoding="utf-8")
    assert p4.load_mandatory(path) == ({2: item}, p4.sha256_file(path))
    path.write_text(json.dumps([item, item]), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        p4.load_mandatory(path)
    for value in ({}, None, "array", 1, True):
        path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(TypeError, match="explicit JSON array"):
            p4.load_mandatory(path)
    path.write_text(json.dumps([{}]), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid mandatory inclusion"):
        p4.load_mandatory(path)


@pytest.mark.parametrize("directory,link_part", [
    ("build/p4", "build"), ("build/p4", "build/p4"),
    ("reports/P4", "reports"), ("reports/P4", "reports/P4"),
    ("build/p4", "build/p4/nested"),
])
def test_output_rejects_symlink_ancestors(tmp_path, directory, link_part):
    outside = tmp_path / "external"
    outside.mkdir()
    link = tmp_path / link_part
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="symlink/junction"):
        p4.contained_output(tmp_path / directory / "nested/pilot.jsonl", directory)
    assert not list(outside.iterdir())


def test_output_boundaries_and_junction(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="under build/p4"):
        p4.contained_output(tmp_path / "outside.jsonl", "build/p4")
    ancestor = tmp_path / "build"
    monkeypatch.setattr(p4.os.path, "isjunction", lambda path: path == ancestor, raising=False)
    with pytest.raises(ValueError, match="symlink/junction"):
        p4.contained_output(tmp_path / "build/p4/pilot.jsonl", "build/p4")


def test_dedup_disk_location_and_cleanup(snapshot, monkeypatch):
    original_connect, scratch_paths = p4.sqlite3.connect, []
    def tracked_connect(path, *args, **kwargs):
        if str(path).endswith("seen.sqlite"):
            scratch_paths.append(Path(path))
            assert Path(path).is_relative_to(p4.ROOT / "build/p4")
        return original_connect(path, *args, **kwargs)
    monkeypatch.setattr(p4.sqlite3, "connect", tracked_connect)
    with opened(snapshot) as (conn, _):
        documents = p4.eligible(conn, p4.source_metadata(conn))
        assert next(documents)["document_id"] == 1
        assert scratch_paths[0].is_file()
        documents.close()
        assert not scratch_paths[0].parent.exists()
        sources = p4.source_metadata(conn)
        del sources["bangumi"]
        with pytest.raises(ValueError, match="source/evidence"):
            list(p4.eligible(conn, sources))
    assert len(scratch_paths) == 2
    assert not list((p4.ROOT / "build/p4").iterdir())
