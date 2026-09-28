"""Fetch only source files discovered in the recorded tree at its pinned revision."""
import hashlib
import json
from pathlib import Path
import urllib.request

root = Path("reports/P1/public-audit")
tree = json.loads((root / "moegirl_tree.json").read_text(encoding="utf-8"))
results = []
for node in tree["tree"]:
    path = node["path"]
    if path.endswith(("dump_converter.py", "moegirl_mapper.py")):
        url = f"https://raw.githubusercontent.com/Zzzzzzyt/moegirl-dataset/{tree['sha']}/{path}"
        with urllib.request.urlopen(url, timeout=25) as response:
            raw = response.read(1_000_000)
        dest = path.replace("/", "_") + ".txt"
        (root / dest).write_bytes(raw)
        results.append({"path": path, "revision": tree["sha"], "url": url,
                        "sha256": hashlib.sha256(raw).hexdigest(), "artifact": dest})
(root / "pinned-source-requests.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results))
