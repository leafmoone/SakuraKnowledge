"""Audit the frozen trusted-text census without semantic execution or snapshot writes."""
import argparse
import json
from collections import Counter
from contextlib import closing
from pathlib import Path

from p4_corpus import (
    DEFAULT_CONFIG,
    ROOT,
    eligible,
    load_config,
    source_metadata,
    stratum,
    verified_snapshot,
    verify_census,
)


def audit(snapshot, config, config_hash):
    expected = config["snapshot"]
    with verified_snapshot(snapshot, expected["sha256"], expected["size"]) as (conn, binding):
        sources = source_metadata(conn)
        census = Counter()
        with closing(eligible(conn, sources)) as documents:
            for doc in documents:
                census[stratum(doc, config)] += 1
        verify_census(census, config)
        statuses = [list(row) for row in conn.execute(
            "SELECT source_id,status,count(*) FROM documents GROUP BY source_id,status")]
    # PASS is constructed only after post-close SHA and sidecar verification succeeds.
    return {"version": config["version"], "config_sha256": config_hash,
            "snapshot": {"path": str(snapshot), **binding},
            "index_episodes": False, "trusted_text_census": dict(census),
            "eligible_total": sum(census.values()), "expected_total": config["eligible_total"],
            "documents_by_source_status": statuses,
            "semantic_ineligible": config["semantic_ineligible"],
            "coverage_gate": "PASS", "snapshot_sha256_unchanged": True,
            "sidecars_unchanged": True, "semantic_execution": "NOT_RUN",
            "limitation": "Stored document status is authoritative; payload claims do not "
                          "upgrade trust. Census covers only trusted text, not all source families. "
                          "Pre/post verification does not exclude transient concurrent writes."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--snapshot", type=Path,
                        help="optional relocated snapshot; configured SHA/size still mandatory")
    args = parser.parse_args(argv)
    config, digest = load_config(args.config)
    snapshot = args.snapshot or ROOT / config["snapshot"]["path"]
    try:
        result = audit(snapshot, config, digest)
    except ValueError as exc:
        print(json.dumps({"coverage_gate": "FAIL", "error": str(exc),
                          "semantic_execution": "NOT_RUN"}))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
