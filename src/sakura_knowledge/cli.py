"""JSON-only stdout; offline queries. Metadata refresh is explicitly opt-in."""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from .api import Knowledge
from .model import EntryKey
from .storage import build, digest, load_manifest, verify

LATEST_URL = "https://raw.githubusercontent.com/bangumi/Archive/master/aux/latest.json"


def check_latest(output):
    result = {"url": LATEST_URL, "checked_at_utc": datetime.now(UTC).isoformat(),
              "status": "failed"}
    try:
        with urllib.request.urlopen(LATEST_URL, timeout=30) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ValueError("metadata response too large")
            result.update(status="checked", http_status=response.status,
                          metadata=json.loads(raw))
    except (OSError, ValueError, urllib.error.URLError) as exc:
        result["error"] = str(exc)
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sknow")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("manifest")
    sources = sub.add_parser("sources")
    sources.add_argument("action", choices=["check"])
    sources.add_argument("--output", default="metadata/bangumi-latest.json")
    builder = sub.add_parser("build")
    builder.add_argument("manifest")
    builder.add_argument("output")
    verifier = sub.add_parser("verify")
    verifier.add_argument("database")
    for name in ("lookup", "search", "related", "ask"):
        command = sub.add_parser(name)
        command.add_argument("database")
        command.add_argument("query")
        command.add_argument("--kind")
        command.add_argument("--namespace")
        if name in {"lookup", "related"}:
            command.add_argument("--key", action="store_true",
                                 help="query is exact value; requires kind and namespace")
        if name in {"search", "related"}:
            command.add_argument("--limit", type=int, default=20)
        if name == "related":
            command.add_argument("--relation")
    args = parser.parse_args(argv)
    try:
        if args.command == "sources":
            result = check_latest(args.output)
        elif args.command == "inspect":
            data, sha = load_manifest(args.manifest)
            result = {"manifest_sha256": sha, "sources": [
                {"source_id": s["source_id"], "exists": Path(s["path"]).is_file(),
                 "digest_matches": digest(s["path"]) == s["local_sha256"]
                 if Path(s["path"]).is_file() else False} for s in data["sources"]]}
        elif args.command == "build":
            result = build(args.manifest, args.output)
        elif args.command == "verify":
            result = verify(args.database)
        else:
            with Knowledge(args.database) as knowledge:
                if args.command == "related" or getattr(args, "key", False):
                    if not args.kind or not args.namespace:
                        raise ValueError("exact key requires --kind and --namespace")
                    key = EntryKey(args.kind, args.namespace, args.query)
                    result = (knowledge.related(key, relation=args.relation, limit=args.limit)
                              if args.command == "related" else knowledge.lookup(key=key))
                else:
                    options = {"kind": args.kind, "namespace": args.namespace}
                    if args.command == "search":
                        options["topk"] = args.limit
                    result = getattr(knowledge, args.command)(args.query, **options)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result.get("ok") is False or result.get("status") == "failed" else 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
