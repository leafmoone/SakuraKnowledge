"""P4 offline preparation, never a production semantic runtime.

Run from any working directory; paths below are relative to this project:
  python tools/p4_model_assets.py inspect intfloat/multilingual-e5-small --output model/meta.json
  python tools/p4_model_assets.py freeze intfloat/multilingual-e5-small --contract model/contract.json \
      --file tokenizer.json --file config.json --file model.safetensors --output model/plan.json
  python tools/p4_model_assets.py download --plan model/plan.json --output model/download-001.json
  python tools/p4_model_assets.py verify --plan model/plan.json --receipt model/download-001.json \
      --output model/verify-001.json

Freeze requires an explicit reviewed contract JSON, never guessed pooling:
{"source": "explicit_config", "review_note": "Explain official documentation review",
 "dimension": 384, "max_sequence_tokens": 512, "pooling": "mean",
 "normalize": true, "query_prefix": "query: ", "passage_prefix": "passage: ",
 "tokenizer_files": ["tokenizer.json"]}
These are illustrative values, NOT verified contracts or defaults. Explicitly select
all needed tokenizer/config/weight/card/license files. Validation checks the contract
schema, not its factual correctness: review official documentation before freezing.
No code imports from models, weight deserialization, inference, or runtime completeness
checks occur. License metadata is recorded, not legal approval. Missing upstream SHA256
remains null; actual byte hashes belong only to download receipts. Plans and receipts
are create-new; failures/partial assets remain preserved, never silently replaced.
Verification is strictly local. Operate in an exclusively owned project tree; hostile
concurrent filesystem mutation is not supported. HTTP uses no configured credentials;
only HTTPS Hugging Face hosts/CDNs are allowed (other redirects fail closed).
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

REPOSITORIES = {"intfloat/multilingual-e5-small", "BAAI/bge-m3"}
PROJECT = Path(__file__).resolve().parents[1]
REVISION = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)),
            *(f"LPT{i}" for i in range(10))}
FAILURES = (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError,
            http.client.HTTPException)


class AssetError(ValueError):
    """A fixed error code, never raw upstream text or URLs."""


def require(condition, code):
    if not condition:
        raise AssetError(code)


def relative_name(name):
    require(isinstance(name, str) and bool(name), "invalid_path")
    parts = name.split("/")
    for part in parts:
        require(bool(re.fullmatch(r"[A-Za-z0-9_.-]+", part))
                and part not in {".", ".."} and not part.endswith(".")
                and part.split(".")[0].upper() not in RESERVED, "invalid_path")
    return parts


def contained(project, name, *, output=False):
    parts = relative_name(name)
    require(not output or parts[0] == "model", "output_outside_model")
    root = Path(project).resolve()
    current = root
    for part in parts:
        current = current / part
        require(not current.is_symlink(), "symlink_forbidden")
        # Windows junctions are reparse points too, not necessarily symlinks.
        if current.exists():
            require(not (getattr(current.lstat(), "st_file_attributes", 0) & 0x400),
                    "symlink_forbidden")
        require(current.resolve().is_relative_to(root), "path_escape")
    return current


def read_json(project, name):
    with contained(project, name).open(encoding="utf-8") as stream:
        return json.load(stream)


def reserve_output(project, name):
    path = contained(project, name, output=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("x", encoding="utf-8")


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def allowed_url(url):
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    require(parsed.scheme == "https" and parsed.username is None
            and parsed.password is None and parsed.port in {None, 443}
            and (host in {"huggingface.co", "hf.co"}
                 or host.endswith((".huggingface.co", ".hf.co"))), "unsafe_redirect")
    if "/resolve/" in parsed.path:
        revision = parsed.path.split("/resolve/", 1)[1].split("/", 1)[0]
        require(bool(REVISION.fullmatch(revision)), "unpinned_asset_url")


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        if "/resolve/" in req.full_url and "/resolve/" in newurl:
            original = urllib.parse.urlsplit(req.full_url).path
            redirected = urllib.parse.urlsplit(newurl).path
            require(original == redirected, "redirect_identity_mismatch")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url):
    allowed_url(url)
    # Ignore environment proxy credentials as well as hub caches/tokens.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), OfficialRedirect())
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "P4-assets/1"}),
                       timeout=60)


def api_json(url, opener=open_url):
    with opener(url) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    require(len(data) <= 16 * 1024 * 1024, "metadata_too_large")
    result = json.loads(data)
    require(isinstance(result, dict), "invalid_metadata")
    return result


def resolve(repo, opener=open_url):
    require(repo in REPOSITORIES, "repository_not_allowlisted")
    base = f"https://huggingface.co/api/models/{repo}"
    initial = api_json(base, opener)
    revision = initial.get("sha")
    require(isinstance(revision, str) and bool(REVISION.fullmatch(revision)),
            "invalid_revision")
    metadata = api_json(f"{base}/revision/{revision}?blobs=true", opener)
    require(metadata.get("sha") == revision and metadata.get("id") == repo,
            "metadata_identity_mismatch")
    card = metadata.get("cardData") or {}
    require(isinstance(card, dict), "invalid_metadata")
    return {"repository": repo, "revision": revision,
            "license_metadata": {"source": f"{base}/revision/{revision}",
                                 "card_data": {key: card.get(key) for key in
                                               ("license", "license_name", "license_link")},
                                 "review_status": "NOT_REVIEWED"},
            "siblings": metadata.get("siblings", [])}


def validate_contract(contract, names):
    require(isinstance(contract, dict), "invalid_contract")
    required = {"source", "review_note", "dimension", "max_sequence_tokens", "pooling",
                "normalize", "query_prefix", "passage_prefix", "tokenizer_files"}
    require(set(contract) == required and contract["source"] == "explicit_config",
            "invalid_contract")
    require(isinstance(contract["review_note"], str) and bool(contract["review_note"].strip()),
            "contract_review_required")
    for key in ("dimension", "max_sequence_tokens"):
        require(type(contract[key]) is int and 0 < contract[key] <= 10_000_000,
                "invalid_contract")
    require(isinstance(contract["pooling"], str)
            and contract["pooling"] in {"mean", "cls", "last_token", "max"}
            and type(contract["normalize"]) is bool, "invalid_contract")
    require(all(isinstance(contract[key], str) for key in ("query_prefix", "passage_prefix")),
            "invalid_contract")
    tokens = contract["tokenizer_files"]
    require(isinstance(tokens, list) and bool(tokens)
            and all(isinstance(item, str) and item in names for item in tokens)
            and len(tokens) == len(set(tokens)), "invalid_tokenizer_contract")


def validate_expected(entries):
    require(isinstance(entries, list) and bool(entries), "empty_inventory")
    seen = set()
    for item in entries:
        require(isinstance(item, dict)
                and set(item) == {"path", "size", "sha256", "git_blob_sha1"},
                "invalid_inventory")
        name = item["path"]
        relative_name(name)
        require(name.casefold() not in seen, "duplicate_path")
        seen.add(name.casefold())
        require(type(item["size"]) is int and item["size"] >= 0, "invalid_size")
        for key, pattern in (("sha256", SHA256), ("git_blob_sha1", REVISION)):
            require(item[key] is None or (isinstance(item[key], str)
                    and bool(pattern.fullmatch(item[key]))), "invalid_hash")
    for name in seen:
        require(not any(parent in seen for parent in
                        ("/".join(name.split("/")[:i]) for i in range(1, len(name.split("/"))))),
                "path_conflict")


def freeze(metadata, names, contract):
    require(isinstance(names, list) and bool(names), "empty_inventory")
    siblings = metadata["siblings"]
    require(isinstance(siblings, list), "invalid_metadata")
    indexed = {}
    for item in siblings:
        require(isinstance(item, dict) and isinstance(item.get("rfilename"), str),
                "invalid_metadata")
        require(item["rfilename"] not in indexed, "duplicate_metadata_path")
        indexed[item["rfilename"]] = item
    entries = []
    for name in names:
        relative_name(name)
        require(name in indexed, "file_not_in_metadata")
        info = indexed[name]
        lfs = info.get("lfs") or {}
        require(isinstance(lfs, dict), "invalid_metadata")
        entries.append({"path": name, "size": info.get("size", lfs.get("size")),
                        "sha256": lfs.get("sha256"),
                        "git_blob_sha1": None if lfs else info.get("blobId")})
    entries.sort(key=lambda item: item["path"])
    plan = {"schema": "p4-model-plan-v1", "repository": metadata["repository"],
            "revision": metadata["revision"], "expected": entries,
            "license_metadata": metadata["license_metadata"], "contract": contract}
    validate_plan(plan)
    return plan


def validate_plan(plan):
    require(isinstance(plan, dict) and plan.get("schema") == "p4-model-plan-v1",
            "invalid_plan")
    require(isinstance(plan.get("repository"), str)
            and plan["repository"] in REPOSITORIES, "repository_not_allowlisted")
    require(isinstance(plan.get("revision"), str)
            and bool(REVISION.fullmatch(plan["revision"])), "invalid_revision")
    validate_expected(plan.get("expected"))
    validate_contract(plan.get("contract"), {item["path"] for item in plan["expected"]})
    require(isinstance(plan.get("license_metadata"), dict), "invalid_license_metadata")


def asset_name(plan, name):
    return f"model/{plan['repository'].replace('/', '--')}/{plan['revision']}/{name}"


def inventory_file(path):
    require(path.is_file(), "not_regular_file")
    size = path.stat().st_size
    sha = hashlib.sha256()
    blob = hashlib.sha1(f"blob {size}\0".encode(), usedforsecurity=False)
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            sha.update(chunk)
            blob.update(chunk)
    return {"size": size, "sha256": sha.hexdigest(), "git_blob_sha1": blob.hexdigest()}


def check_expected(item, actual):
    require(actual["size"] == item["size"], "size_mismatch")
    for key in ("sha256", "git_blob_sha1"):
        require(item[key] is None or item[key] == actual[key], "hash_mismatch")


def safe_error(exc):
    return str(exc) if isinstance(exc, AssetError) else "operation_failed"


def download(project, plan, opener=open_url):
    validate_plan(plan)
    result = {"schema": "p4-model-download-v1", "plan_sha256": digest(plan),
              "obtained": [], "errors": [], "status": "FAILED"}
    for item in plan["expected"]:
        try:
            path = contained(project, asset_name(plan, item["path"]), output=True)
            if path.exists():
                require(path.is_file(), "not_regular_file")
                require(item["sha256"] is not None or item["git_blob_sha1"] is not None,
                        "existing_file_without_expected_hash")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                url = (f"https://huggingface.co/{plan['repository']}/resolve/"
                       f"{plan['revision']}/{urllib.parse.quote(item['path'], safe='/')}")
                with opener(url) as response, path.open("xb") as stream:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        require(total <= item["size"], "size_mismatch")
                        stream.write(chunk)
            actual = inventory_file(path)
            result["obtained"].append({"path": item["path"], **actual})
            check_expected(item, actual)
        except FAILURES as exc:
            result["errors"].append({"path": item["path"], "code": safe_error(exc)})
    result["status"] = "PASS" if not result["errors"] else "FAILED"
    result["inventory_sha256"] = digest(result["obtained"])
    return result


def walk_error(exc):
    raise AssetError("inventory_walk_failed") from None


def verify(project, plan, receipt):
    validate_plan(plan)
    require(isinstance(receipt, dict) and receipt.get("schema") == "p4-model-download-v1"
            and receipt.get("status") == "PASS" and receipt.get("errors") == []
            and receipt.get("plan_sha256") == digest(plan), "invalid_receipt")
    obtained = receipt.get("obtained")
    validate_expected(obtained)
    require(all(item["sha256"] is not None for item in obtained), "missing_obtained_hash")
    require(receipt.get("inventory_sha256") == digest(obtained), "inventory_digest_mismatch")
    require([item["path"] for item in obtained] == [item["path"] for item in plan["expected"]],
            "inventory_membership_mismatch")
    result = {"schema": "p4-model-verification-v1", "plan_sha256": digest(plan),
              "receipt_sha256": digest(receipt), "status": "FAILED", "errors": []}
    for expected, recorded in zip(plan["expected"], obtained, strict=True):
        try:
            path = contained(project, asset_name(plan, expected["path"]), output=True)
            require(path.is_file(), "missing_file")
            actual = inventory_file(path)
            check_expected(expected, actual)
            check_expected(recorded, actual)
        except FAILURES as exc:
            result["errors"].append({"path": expected["path"], "code": safe_error(exc)})
    # Strict membership: reject extra bytes, partials and links, including junctions.
    try:
        root = contained(project, asset_name(plan, "placeholder"), output=True).parent
        planned = {item["path"] for item in plan["expected"]}
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            for name in dirs + files:
                path = Path(directory) / name
                relative = path.relative_to(root).as_posix()
                contained(project, asset_name(plan, relative), output=True)
                require(path.is_dir() or (path.is_file() and relative in planned),
                        "unexpected_file")
    except FAILURES as exc:
        result["errors"].append({"code": safe_error(exc)})
    result["status"] = "PASS" if not result["errors"] else "FAILED"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subs = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "freeze", "download", "verify"):
        sub = subs.add_parser(command)
        sub.add_argument("--output", required=True, help="create-new project model/ JSON")
        if command in {"inspect", "freeze"}:
            sub.add_argument("repository", choices=sorted(REPOSITORIES))
        if command == "freeze":
            sub.add_argument("--contract", required=True)
            sub.add_argument("--file", action="append", required=True, dest="files")
        if command in {"download", "verify"}:
            sub.add_argument("--plan", required=True)
        if command == "verify":
            sub.add_argument("--receipt", required=True)
    args = parser.parse_args(argv)
    try:
        # Reserve before network or writes so a colliding receipt never starts work.
        with reserve_output(PROJECT, args.output) as output:
            try:
                if args.command == "inspect":
                    result = resolve(args.repository)
                elif args.command == "freeze":
                    contract = read_json(PROJECT, args.contract)
                    validate_contract(contract, set(args.files))
                    result = freeze(resolve(args.repository), args.files, contract)
                elif args.command == "download":
                    result = download(PROJECT, read_json(PROJECT, args.plan))
                else:
                    result = verify(PROJECT, read_json(PROJECT, args.plan),
                                    read_json(PROJECT, args.receipt))
            except FAILURES as exc:
                result = {"status": "FAILED", "errors": [{"code": safe_error(exc)}]}
            output.write(json.dumps(result, ensure_ascii=True, indent=2) + "\n")
        return 1 if result.get("status") == "FAILED" else 0
    except FAILURES as exc:
        print(json.dumps({"status": "FAILED", "errors": [{"code": safe_error(exc)}]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
