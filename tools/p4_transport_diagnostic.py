"""One explicitly authorized ef2048 P4-110 transport diagnostic, exclusive evidence."""
import copy
import json
import shutil
import tempfile
import time
from pathlib import Path

from tools import p4_full_acceptance as a
from tools import p4_full_build as b
from tools import p4_rust_pilot as p


def main():
    root = b.ROOT
    old = root / 'build/p4-prepared-lexical-5c8526e-v1'
    target = root / 'build/p4-transport-ef2048-f2bdc11-v1'
    destination = root / 'reports/P4/transport-f2bdc11'
    destination.mkdir(exist_ok=False)
    config_path = root / 'configs/p4-ef2048-transport-experiment.json'
    config = b.read_json(config_path)
    declaration = b.full.validate_contract(config, expected_expansion_search=2048)
    manifest = copy.deepcopy(b.read_json(old / 'manifest.json'))
    manifest['canonical_contract'] = {'schema': config['schema'], **b.binding(config_path, root)}
    manifest['declarative_contract'] = declaration
    manifest['contract'] = a.runtime_contract(declaration, manifest['full_chunk_count'])
    for record in [manifest['snapshot'], *[v for k, v in manifest['artifacts'].items() if k != 'external_data'], *manifest['artifacts']['external_data']]:
        if record['path'] != 'lexical-membership.sqlite':
            b.rebase_prepared_binding(record, old, target, external_dll=record is manifest['artifacts']['ort_dll'])
    stage = Path(tempfile.mkdtemp(prefix=target.name + '.stage-', dir=target.parent))
    shutil.copyfile(old / 'lexical-membership.sqlite', stage / 'lexical-membership.sqlite')
    a.validate_prepared_membership(stage / 'lexical-membership.sqlite', manifest)
    b.save_new(stage / 'manifest.json', manifest)
    stage.rename(target)
    binary = root / 'build/p4-transport-ef2048-f2bdc11/rust-target/release/semantic_pilot.exe'
    case = next(c for c in b.read_json(root / 'reports/P4/retrieval-gold.json')['cases'] if c['case_id'] == 'P4-110')
    report = {'binary': str(binary), 'experimental_ef2048': True, 'actual_ef': 2048, 'candidate': str(target), 'full120': 'NOT_RUN'}
    with a.AcceptanceSession() as session:
        report['verified_records'] = a.validate_full_manifest(manifest, config, pack_root=target, session=session, experimental_ef2048=True)
        with (destination / 'stderr.log').open('xb') as stderr:
            driver = p.Driver([str(binary), str(root / config['snapshot']['path']), str(target / 'manifest.json')], stderr)
            try:
                report['open'], _ = driver.receive(120)
                start = time.perf_counter()
                response, size = driver.request(case)
                report['wall_ms'] = (time.perf_counter() - start) * 1000
                report['response_bytes'] = size
                report['response'] = response
                with (destination / 'response.jsonl').open('xb') as stream:
                    stream.write(driver.last_raw)
            except Exception as exc:  # noqa: BLE001 - exclusive diagnostic retains failure
                report['error'] = str(exc)
                report['transport_failure'] = driver.transport_failure
                with (destination / 'transport-prefix.bin').open('xb') as stream:
                    stream.write(driver.last_raw[:p.MAX_BYTES + 1])
            finally:
                report['shutdown'] = driver.close(terminal='error' in report)
    b.save_new(destination / 'diagnostic.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('response', 'open')}))


if __name__ == '__main__':
    main()
