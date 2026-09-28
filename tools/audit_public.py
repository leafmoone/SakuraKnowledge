"""Explicit metadata/source-code audit; never fetches datasets or runs upstream code."""
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

URLS = {
    "moegirl_tree": "https://api.github.com/repos/Zzzzzzyt/moegirl-dataset/git/trees/main?recursive=1",
    "dump_converter": "https://raw.githubusercontent.com/Zzzzzzyt/moegirl-dataset/main/bangumi/dump_converter.py",
    "moegirl_mapper": "https://raw.githubusercontent.com/Zzzzzzyt/moegirl-dataset/main/bangumi/moegirl_mapper.py",
}


def main():
    output = Path("reports/P1/public-audit")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for name, url in URLS.items():
        item = {"name": name, "url": url,
                "inspected_at_utc": datetime.now(UTC).isoformat()}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "SakuraKnowledge-audit"})
            with urllib.request.urlopen(request, timeout=25) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError("audit response exceeds cap")
                item.update(http_status=response.status, size=len(raw),
                            sha256=hashlib.sha256(raw).hexdigest())
                filename = name + (".json" if name.endswith("tree") else ".txt")
                (output / filename).write_bytes(raw)
                item["artifact"] = filename
        except (OSError, ValueError) as exc:
            item["error"] = str(exc)
        results.append(item)
    (output / "requests.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results))


if __name__ == "__main__":
    main()
