"""Synthetic-only tests: never open the FULL snapshot."""
import importlib.util
import json
import sqlite3
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
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO build_meta VALUES('index_episodes','false')")
    for sid in ("bangumi", "moegirl", "danbooru", "tag_wiki"):
        conn.execute("INSERT INTO sources VALUES(?,?)",
                     (sid, json.dumps({"provider": sid, "repo": "fixture", "source_id": sid})))
    for did in range(1, 441):
        sid = ("bangumi", "moegirl", "danbooru", "tag_wiki")[(did - 1) // 110]
        kind = "tag" if sid == "tag_wiki" else "page"
        conn.execute("INSERT INTO entries(id,kind,namespace,value) VALUES(?,?,?,?)",
                     (did, kind, sid, str(did)))
        # Two identity rows deliberately must not double document membership.
        for _ in range(2):
            conn.execute("INSERT INTO entry_evidence(entry_id,source_id,evidence_id,status,payload) "
                         "VALUES(?,?,?,'source_backed','{}')", (did, sid, f"identity:{did}"))
        original = ("中文", "かな", "English", "123")[(did - 1) % 4]
        conn.execute("INSERT INTO documents(id,entry_id,title,original,search_text,language,"
                     "status,source_id,evidence_id,payload) VALUES(?,?,?,?,?,NULL,?,?,?,'{}')",
                     (did, did, f"Title {did}", original, original,
                      "generated_from_evidence" if did % 2 else "source_backed", sid, f"doc:{did}"))
        conn.execute("INSERT INTO search_fts(text,document_id,entry_id) VALUES(?,?,?)",
                     (original, did, did))
    conn.commit()
    conn.close()
    return path


def opened(path):
    return p4.verified_snapshot(path, p4.sha256_file(path), path.stat().st_size)


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
        assert len(docs) == 434
        assert {d["document_id"] for d in docs} == set(range(7, 441))
        assert docs[0]["entry_key"] == {"kind": "page", "namespace": "bangumi", "value": "7"}
        assert docs[0]["evidence_id"] == "doc:7"
        assert "payload" not in docs[0] and "search_text" not in docs[0]
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM documents")
    assert p4.sha256_file(snapshot) == before


def test_deterministic_selection_floors_and_mandatory(snapshot):
    with opened(snapshot) as (conn, _):
        sources = p4.source_metadata(conn)
        a = p4.select(conn, sources, size=420)
        b = p4.select(conn, sources, size=420)
        assert a == b
        ids, reasons, audit = a
        assert len(ids) == len(set(ids)) == 420
        assert audit["eligible_count"] == 440
        docs = [p4.fetch(conn, did, sources) for did in ids]
        assert ids == [d["document_id"] for d in sorted(docs, key=p4.rank)]
        for fam in p4.FAMILIES:
            assert sum(d["source_family"] == fam for d in docs) >= 100
        for script in p4.SCRIPTS:
            assert sum(d["script_label"] == script for d in docs) >= 100
        for kind in ("page", "tag"):
            assert sum(d["entry_key"]["kind"] == kind for d in docs) >= 100
        absent = next(did for did in range(1, 441) if did not in ids)
        mandatory = {absent: {"document_id": absent,
                             "entry_key": p4.fetch(conn, absent, sources)["entry_key"],
                             "role": "hard_negative", "reason": "frozen contrast"}}
        chosen, why, _ = p4.select(conn, sources, size=420, mandatory=mandatory)
        assert absent in chosen and "mandatory:hard_negative" in why[absent]
        assert all(reasons[did] for did in ids)
        with pytest.raises(ValueError, match="insufficient"):
            p4.select(conn, sources)
        with pytest.raises(ValueError, match="exceed"):
            p4.select(conn, sources, size=10)
        mandatory[absent]["entry_key"] = {}
        with pytest.raises(ValueError, match="key mismatch"):
            p4.select(conn, sources, size=420, mandatory=mandatory)
        with pytest.raises(ValueError, match="not eligible"):
            p4.select(conn, sources, size=420, mandatory={999: {}})


def test_snapshot_verification_and_sidecars(snapshot):
    digest = p4.sha256_file(snapshot)
    size = snapshot.stat().st_size
    with (
        pytest.raises(ValueError, match="size mismatch"),
        p4.verified_snapshot(snapshot, digest, size + 1),
    ):
        pass
    with (
        pytest.raises(ValueError, match="SHA256 mismatch"),
        p4.verified_snapshot(snapshot, "0" * 64, size),
    ):
        pass
    for suffix in ("-wal", "-journal"):
        sidecar = Path(str(snapshot) + suffix)
        sidecar.write_bytes(b"not empty")
        with pytest.raises(ValueError, match="nonempty"), opened(snapshot):
            pass
        assert sidecar.read_bytes() == b"not empty"
        sidecar.unlink()
    Path(str(snapshot) + "-wal").touch()
    with opened(snapshot) as (_, binding):
        assert binding["sidecars"]["-wal"] == 0


def test_inspect_cli(snapshot, capsys):
    p4.main(["--snapshot", str(snapshot), "--sha256", p4.sha256_file(snapshot),
             "--size", str(snapshot.stat().st_size), "inspect", "--document-id", "1",
             "--excerpt-chars", "1"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["document_id"] == 1 and doc["original"] == "中"
    assert doc["original_characters"] == 2
    assert doc["source_metadata"]["provider"] == "bangumi"
    assert doc["base_snapshot"]["sha256"] == p4.sha256_file(snapshot)
    assert doc["identity_proof_resolution"] == p4.IDENTITY_RESOLUTION
    assert not list((p4.ROOT / "build/p4").iterdir())


def test_output_boundaries_and_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(p4, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="under build/p4"):
        p4.contained_output(tmp_path / "outside.jsonl", "build/p4")
    target = tmp_path / "build/p4/existing.jsonl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"preserved")
    with pytest.raises(FileExistsError):
        p4.contained_output(target, "build/p4")
    assert target.read_bytes() == b"preserved"


def test_mandatory_input_and_script_heuristic(tmp_path):
    path = tmp_path / "frozen.json"
    item = {"document_id": 2, "entry_key": {"kind": "page", "namespace": "x", "value": "2"},
            "role": "gold_target", "reason": "source anchored"}
    path.write_text(json.dumps([item]), encoding="utf-8")
    loaded, digest = p4.load_mandatory(path)
    assert loaded == {2: item} and digest == p4.sha256_file(path)
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
    assert [p4.script_label(s) for s in ("かな中文", "中文", "abc", "123")] == [
        "kana_present", "han_without_kana", "latin_without_han_kana", "other"]


@pytest.mark.parametrize("field,label", [
    *(('source_family', label) for label in p4.FAMILIES),
    *(('script_label', label) for label in p4.SCRIPTS),
    ("kind", "absent_kind"),
])
def test_missing_required_strata(snapshot, field, label):
    with sqlite3.connect(snapshot) as conn:
        if field == "source_family":
            provider = "tag_wiki" if label == "local_tag" else label
            conn.execute("DELETE FROM search_fts WHERE document_id IN "
                         "(SELECT id FROM documents WHERE source_id=?)", (provider,))
        elif field == "script_label":
            originals = {"kana_present": ("かな",), "han_without_kana": ("中文",),
                         "latin_without_han_kana": ("English", "123")}[label]
            for original in originals:
                conn.execute("DELETE FROM search_fts WHERE document_id IN "
                             "(SELECT id FROM documents WHERE original=?)", (original,))
    with (
        opened(snapshot) as (conn, _),
        pytest.raises(ValueError, match=f"missing required stratum: {field}:{label}"),
    ):
        p4.select(conn, p4.source_metadata(conn), size=1,
                  required_kinds=(label,) if field == "kind" else ())


def test_rare_strata_use_all_available(snapshot):
    with sqlite3.connect(snapshot) as conn:
        conn.execute("DELETE FROM search_fts WHERE document_id > 335")
        conn.execute("UPDATE entries SET kind='rare' WHERE id=1")
        conn.execute("UPDATE documents SET original='English' WHERE original='かな' AND id>2")
    with opened(snapshot) as (conn, _):
        ids, reasons, audit = p4.select(conn, p4.source_metadata(conn), size=330,
                                       required_kinds=("rare",))
        assert audit["eligible_strata"]["source_family"]["local_tag"] == 5
        assert audit["eligible_strata"]["script_label"]["kana_present"] == 1
        assert set(range(331, 336)).issubset(ids)
        assert {1, 2}.issubset(ids)
        assert "floor:kind:rare" in reasons[1]
        assert "floor:script_label:kana_present" in reasons[2]


def test_export_cli_roundtrip(snapshot, monkeypatch, capsys):
    monkeypatch.setattr(p4, "PILOT_SIZE", 420)
    corpus = p4.ROOT / "build/p4/pilot.jsonl"
    manifest = p4.ROOT / "reports/P4/manifest.json"
    before = p4.sha256_file(snapshot)
    args = ["--snapshot", str(snapshot), "--sha256", before,
            "--size", str(snapshot.stat().st_size), "export", "--corpus", str(corpus),
            "--manifest", str(manifest), "--required-kind", "page", "--required-kind", "tag"]
    p4.main(args)
    summary = json.loads(capsys.readouterr().out)
    report = json.loads(manifest.read_bytes())
    docs = [json.loads(line) for line in corpus.read_bytes().splitlines()]
    assert len(docs) == len({d["document_id"] for d in docs}) == 420
    assert report["corpus_sha256"] == summary["corpus_sha256"] == p4.sha256_file(corpus)
    assert report["required_kinds"] == ["page", "tag"]
    assert report["base_snapshot"]["sha256"] == before == p4.sha256_file(snapshot)
    with opened(snapshot) as (conn, _):
        sources = p4.source_metadata(conn)
        ids, reasons, audit = p4.select(conn, sources, size=420)
        assert [d["document_id"] for d in docs] == ids
        assert report["eligible_sha256"] == audit["eligible_sha256"]
        for doc in docs:
            did = doc["document_id"]
            assert doc == {**p4.fetch(conn, did, sources), "selection_reasons": reasons[did]}
            proof = conn.execute(report["identity_proof_resolution"]["sql"],
                                 (doc["identity_proof_ref"]["entry_id"],)).fetchall()
            assert proof and all(row["status"] == "source_backed" for row in proof)
            assert all(row["source_id"] in sources for row in proof)
            assert all(row["evidence_id"] != doc["evidence_id"] for row in proof)
    frozen = corpus.read_bytes(), manifest.read_bytes()
    with pytest.raises(FileExistsError):
        p4.main(args)
    assert frozen == (corpus.read_bytes(), manifest.read_bytes())


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
    target = tmp_path / directory / "nested/pilot.jsonl"
    with pytest.raises(ValueError, match="symlink/junction"):
        p4.contained_output(target, directory)
    assert not list(outside.iterdir())


def test_output_rejects_junction_ancestor(tmp_path, monkeypatch):
    ancestor = tmp_path / "build"
    monkeypatch.setattr(p4.os.path, "isjunction", lambda path: path == ancestor)
    with pytest.raises(ValueError, match="symlink/junction"):
        p4.contained_output(tmp_path / "build/p4/pilot.jsonl", "build/p4")


def test_dedup_disk_location_and_cleanup(snapshot, monkeypatch):
    original_connect = p4.sqlite3.connect
    scratch_paths = []

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
