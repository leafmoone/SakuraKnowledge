"""Synthetic offline preparation tests; no weights, runtime, network, or database."""

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "p4_model_assets", Path(__file__).resolve().parents[1] / "tools/p4_model_assets.py"
)
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)
REV = "a" * 40
REPO = "intfloat/multilingual-e5-small"
DATA = b"synthetic tokenizer bytes"


def contract():
    return {"source": "explicit_config", "review_note": "Synthetic explicit test configuration",
            "dimension": 3, "max_sequence_tokens": 32, "pooling": "cls", "normalize": True,
            "query_prefix": "q: ", "passage_prefix": "", "tokenizer_files": ["tokenizer.json"]}


def metadata():
    return {"repository": REPO, "revision": REV,
            "license_metadata": {"card_data": {"license": "mit"},
                                 "review_status": "NOT_REVIEWED"},
            "siblings": [{"rfilename": "tokenizer.json", "size": len(DATA),
                          "lfs": {"sha256": hashlib.sha256(DATA).hexdigest()}}]}


def plan():
    return assets.freeze(metadata(), ["tokenizer.json"], contract())


def fake_open(url):
    assert url == f"https://huggingface.co/{REPO}/resolve/{REV}/tokenizer.json"
    return io.BytesIO(DATA)


def test_resolve_immutable_metadata_before_any_asset_download():
    calls = []

    def opener(url):
        calls.append(url)
        if len(calls) == 1:
            return io.BytesIO(json.dumps({"sha": REV}).encode())
        assert url.endswith(f"/revision/{REV}?blobs=true")
        return io.BytesIO(json.dumps({"id": REPO, "sha": REV,
                                     "cardData": {"license": "mit"},
                                     "siblings": metadata()["siblings"]}).encode())

    resolved = assets.resolve(REPO, opener)
    frozen = assets.freeze(resolved, ["tokenizer.json"], contract())
    assert len(calls) == 2
    assert all("/resolve/" not in url for url in calls)
    assert frozen["revision"] == REV
    assert frozen["license_metadata"]["card_data"]["license"] == "mit"
    assert "obtained" not in frozen


@pytest.mark.parametrize("revision", ["main", "abc", "A" * 40, "a" * 39, None])
def test_refuse_nonimmutable_api_revision(revision):
    with pytest.raises(assets.AssetError, match="invalid_revision"):
        assets.resolve(REPO, lambda url: io.BytesIO(json.dumps({"sha": revision}).encode()))


def test_pinned_metadata_identity_must_match():
    responses = iter([{"sha": REV}, {"sha": "b" * 40, "id": REPO}])
    with pytest.raises(assets.AssetError, match="metadata_identity_mismatch"):
        assets.resolve(REPO, lambda url: io.BytesIO(json.dumps(next(responses)).encode()))


@pytest.mark.parametrize("repo", ["someone/multilingual-e5-small", "../BAAI/bge-m3"])
def test_repository_allowlist_before_network(repo):
    with pytest.raises(assets.AssetError, match="repository_not_allowlisted"):
        assets.resolve(repo, lambda url: pytest.fail("network must not run"))


def test_both_official_repositories_allowed():
    value = metadata()
    value["repository"] = "BAAI/bge-m3"
    frozen = assets.freeze(value, ["tokenizer.json"], contract())
    assert assets.asset_name(frozen, "tokenizer.json").startswith("model/BAAI--bge-m3/")


def test_download_and_strict_local_verification(tmp_path, monkeypatch):
    frozen = plan()
    before = copy.deepcopy(frozen)
    receipt = assets.download(tmp_path, frozen, fake_open)
    assert frozen == before
    assert receipt["status"] == "PASS"
    assert receipt["obtained"][0]["sha256"] == hashlib.sha256(DATA).hexdigest()
    monkeypatch.setattr(assets.urllib.request, "build_opener",
                        lambda *a: pytest.fail("verification must be offline"))
    assert assets.verify(tmp_path, frozen, receipt)["status"] == "PASS"
    stored = tmp_path / assets.asset_name(frozen, "tokenizer.json")
    stored.write_bytes(b"X" * len(DATA))
    result = assets.verify(tmp_path, frozen, receipt)
    assert result["status"] == "FAILED"
    assert result["errors"][0]["code"] == "hash_mismatch"


def test_existing_verified_bytes_reused_never_overwritten(tmp_path):
    frozen = plan()
    assert assets.download(tmp_path, frozen, fake_open)["status"] == "PASS"
    never_network = lambda url: pytest.fail("existing bytes must not be downloaded")
    assert assets.download(tmp_path, frozen, never_network)["status"] == "PASS"
    target = tmp_path / assets.asset_name(frozen, "tokenizer.json")
    target.write_bytes(b"wrong")
    result = assets.download(tmp_path, frozen, never_network)
    assert result["status"] == "FAILED"
    assert target.read_bytes() == b"wrong"
    assert result["obtained"][0]["sha256"] == hashlib.sha256(b"wrong").hexdigest()


def test_git_blob_expectation_for_non_lfs_file(tmp_path):
    value = metadata()
    value["siblings"][0].pop("lfs")
    value["siblings"][0]["blobId"] = hashlib.sha1(
        f"blob {len(DATA)}\0".encode() + DATA, usedforsecurity=False
    ).hexdigest()
    frozen = assets.freeze(value, ["tokenizer.json"], contract())
    assert frozen["expected"][0]["sha256"] is None
    assert assets.download(tmp_path, frozen, fake_open)["status"] == "PASS"
    assert assets.download(tmp_path, frozen, lambda url: pytest.fail("no network"))["status"]


def test_absent_upstream_sha_stays_null_and_existing_unverifiable_refused(tmp_path):
    frozen = plan()
    frozen["expected"][0]["sha256"] = None
    receipt = assets.download(tmp_path, frozen, fake_open)
    assert receipt["status"] == "PASS"
    assert frozen["expected"][0]["sha256"] is None
    assert assets.verify(tmp_path, frozen, receipt)["status"] == "PASS"
    again = assets.download(tmp_path, frozen, lambda url: pytest.fail("no network"))
    assert again["errors"][0]["code"] == "existing_file_without_expected_hash"


@pytest.mark.parametrize("name", ["../escape", "/absolute", "a/../b", "a\\b", "C:/x",
                                  "a//b", "a/./b", "CON.txt", "file.", "x:stream", ""])
def test_reject_traversal_and_platform_unsafe_paths(tmp_path, name):
    with pytest.raises(assets.AssetError, match="invalid_path"):
        assets.contained(tmp_path, name)
    frozen = plan()
    frozen["expected"][0]["path"] = name
    with pytest.raises(assets.AssetError):
        assets.download(tmp_path, frozen, lambda url: pytest.fail("no network"))


def test_output_must_be_inside_model(tmp_path):
    with pytest.raises(assets.AssetError, match="output_outside_model"):
        assets.reserve_output(tmp_path, "elsewhere/receipt.json")


def test_duplicate_and_conflicting_paths():
    frozen = plan()
    for name, error in [("TOKENIZER.json", "duplicate_path"),
                        ("tokenizer.json/subfile", "path_conflict")]:
        entries = frozen["expected"] + [{**frozen["expected"][0], "path": name}]
        with pytest.raises(assets.AssetError, match=error):
            assets.validate_expected(entries)


def test_symlink_model_directory_rejected(tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    try:
        (tmp_path / "model").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is not permitted by this platform")
    receipt = assets.download(tmp_path, plan(), lambda url: pytest.fail("no network"))
    assert receipt["errors"][0]["code"] == "symlink_forbidden"
    assert not list(target.iterdir())


@pytest.mark.parametrize("mutation", ["missing", "extra", "receipt", "plan", "hash"])
def test_verification_fails_closed(tmp_path, mutation):
    frozen = plan()
    receipt = assets.download(tmp_path, frozen, fake_open)
    target = tmp_path / assets.asset_name(frozen, "tokenizer.json")
    if mutation == "missing":
        target.unlink()
    elif mutation == "extra":
        target.with_name("unexpected.bin").write_bytes(b"extra")
    elif mutation == "receipt":
        receipt["obtained"] = []
    elif mutation == "plan":
        frozen["contract"]["pooling"] = "mean"
    else:
        receipt["obtained"][0]["sha256"] = None
        receipt["inventory_sha256"] = assets.digest(receipt["obtained"])
    if mutation in {"receipt", "plan", "hash"}:
        with pytest.raises(assets.AssetError):
            assets.verify(tmp_path, frozen, receipt)
    else:
        assert assets.verify(tmp_path, frozen, receipt)["status"] == "FAILED"


@pytest.mark.parametrize("key,value", [("pooling", "guess"), ("normalize", "yes"),
                                       ("dimension", True), ("max_sequence_tokens", 0),
                                       ("review_note", ""), ("tokenizer_files", ["missing"]),
                                       ("source", "inferred"), ("query_prefix", None)])
def test_contract_is_explicit_validated_not_guessed(key, value):
    config = contract()
    config[key] = value
    with pytest.raises(assets.AssetError):
        assets.freeze(metadata(), ["tokenizer.json"], config)


def test_errors_do_not_leak_secrets_and_missing_has_no_fake_hash(tmp_path):
    def failing(url):
        raise OSError("Bearer TOP_SECRET https://host/?token=SECRET")

    result = assets.download(tmp_path, plan(), failing)
    assert result["status"] == "FAILED"
    assert result["obtained"] == []
    assert result["errors"] == [{"path": "tokenizer.json", "code": "operation_failed"}]
    assert "SECRET" not in json.dumps(result)


def test_failed_short_download_preserved_not_replaced(tmp_path):
    frozen = plan()
    receipt = assets.download(tmp_path, frozen, lambda url: io.BytesIO(b"short"))
    assert receipt["status"] == "FAILED"
    target = tmp_path / assets.asset_name(frozen, "tokenizer.json")
    assert target.read_bytes() == b"short"
    again = assets.download(tmp_path, frozen, lambda url: pytest.fail("no overwrite"))
    assert again["status"] == "FAILED"
    assert target.read_bytes() == b"short"


@pytest.mark.parametrize("url", ["http://huggingface.co/a", "https://evil.example/a",
                                 "https://huggingface.co.evil.example/a",
                                 "https://user:secret@huggingface.co/a",
                                 "https://huggingface.co/x/y/resolve/main/file"])
def test_redirect_security(url):
    with pytest.raises(assets.AssetError):
        assets.allowed_url(url)


def test_signed_official_cdn_redirect_allowed():
    assets.allowed_url("https://cas-bridge.xethub.hf.co/object?signature=not-recorded")


def test_cli_receipts_are_create_new_and_failure_is_redacted(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "PROJECT", tmp_path)
    monkeypatch.setattr(assets, "resolve",
                        lambda repo: (_ for _ in ()).throw(OSError("SECRET")))
    args = ["inspect", REPO, "--output", "model/inspection.json"]
    assert assets.main(args) == 1
    target = tmp_path / "model/inspection.json"
    original = target.read_bytes()
    assert b"SECRET" not in original
    assert json.loads(original)["status"] == "FAILED"
    monkeypatch.setattr(assets, "resolve", lambda repo: pytest.fail("do not contact network"))
    assert assets.main(args) == 1
    assert target.read_bytes() == original


def test_cli_verify_offline_and_preserves_old_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "PROJECT", tmp_path)
    frozen = plan()
    receipt = assets.download(tmp_path, frozen, fake_open)
    for name, value in [("plan.json", frozen), ("receipt.json", receipt)]:
        (tmp_path / "model" / name).write_text(json.dumps(value), encoding="utf-8")
    args = ["verify", "--plan", "model/plan.json", "--receipt", "model/receipt.json",
            "--output", "model/verification.json"]
    assert assets.main(args) == 0
    assert json.loads((tmp_path / "model/verification.json").read_text())["status"] == "PASS"
    assert json.loads((tmp_path / "model/receipt.json").read_text()) == receipt
