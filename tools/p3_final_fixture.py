"""Supply the omitted text_probe test prerequisite without rebuilding delivery artifacts."""
import json
import time
from pathlib import Path

from p3_final_artifacts import (
    ROOT,
    binding,
    check_binding,
    create_new,
    environment,
    run,
    verify_artifacts,
)


def verify_fixture(art, receipt, artifact_ref):
    directory = Path(art['directory']).resolve()
    expected = {k: art[k] for k in ('binary', 'wheel')}
    manifest = directory / 'source/rust/Cargo.toml'
    probe = Path(art['binary']['path']).parent / 'examples/text_probe.exe'
    sources = {name: directory / ('source/rust/' + path) for name, path in (
        ('example', 'examples/text_probe.rs'), ('runtime', 'src/lib.rs'))}
    if (receipt.get('status') != 'PASS' or receipt.get('source_commit') != art['source_commit'] or
            receipt.get('artifacts') != artifact_ref or receipt.get('before') != expected or
            receipt.get('after') != expected or receipt.get('delivery_artifacts_unchanged') is not True or
            receipt.get('retries') != 0 or receipt.get('FULL_queries') != 0 or
            receipt.get('benchmark_build_or_execution') is not False or
            receipt.get('runtime_or_delivery_rebuild_requested') is not False):
        raise ValueError('fixture provenance or unchanged delivery binding missing')
    proc = receipt['process']
    if (proc['argv'] != ['cargo', 'build', '--manifest-path', str(manifest), '--locked',
                        '--release', '--example', 'text_probe'] or proc['exit'] != 0 or
            Path(proc['environment']['CARGO_TARGET_DIR']).resolve() !=
            Path(art['environment']['CARGO_TARGET_DIR']).resolve() or
            not proc.get('cargo_target_verified') or proc.get('retries') != 0 or
            Path(receipt['probe']['path']).resolve() != probe.resolve()):
        raise ValueError('fixture exact compile contract differs')
    for ref in (*receipt['before'].values(), *receipt['after'].values(), receipt['probe']):
        check_binding(ref)
    for name, path in sources.items():
        ref = receipt['source_bindings'][name]
        if Path(ref['path']).resolve() != path.resolve():
            raise ValueError('fixture source escaped archive')
        check_binding(ref)


def main():
    out = ROOT / 'reports/P3/final-text-probe-prerequisite.json'
    marker = ROOT / 'reports/P3/final-text-probe-prerequisite-start.json'
    if out.exists() or marker.exists():
        raise FileExistsError('fixture prerequisite already reserved; no retry')
    path = ROOT / 'reports/P3/final-artifacts-retry1.json'
    art = json.loads(path.read_bytes())
    verify_artifacts(art)
    directory = Path(art['directory']).resolve()
    target = Path(art['environment']['CARGO_TARGET_DIR']).resolve()
    if not target.is_relative_to(directory) or not directory.is_relative_to(ROOT / 'dist'):
        raise ValueError('fixture Cargo target escaped fixed Knowledge archive')
    source = directory / 'source/rust/examples/text_probe.rs'
    runtime = directory / 'source/rust/src/lib.rs'
    env = environment(target)
    probe = Path(art['binary']['path']).parent / 'examples/text_probe.exe'
    if probe.exists():
        raise FileExistsError('missing prerequisite must be absent before this attempt')
    create_new(marker, {'started_ns': time.time_ns(), 'artifacts': binding(path),
                        'source_commit': art['source_commit'], 'retries': 0})
    before = {k: binding(art[k]['path']) for k in ('binary', 'wheel')}
    sources = {'example': binding(source), 'runtime': binding(runtime)}
    argv = ['cargo', 'build', '--manifest-path', str(directory / 'source/rust/Cargo.toml'),
            '--locked', '--release', '--example', 'text_probe']
    toolchain = []
    for version_argv in ([env['CC'], '--version'], [env['CC'], '-dumpmachine'],
                         [env['CXX'], '--version'], ['rustc', '-vV']):
        observed, _ = run(version_argv, env, ROOT, directory=directory)
        toolchain.append(observed)
        if observed['exit'] != 0:
            raise ValueError('compiler metadata check failed before fixture compile')
    rec, _ = run(argv, env, ROOT, directory=directory)
    result = {'status': 'FAIL', 'process': rec, 'source_commit': art['source_commit'],
              'artifacts': binding(path), 'source_bindings': sources, 'before': before,
              'toolchain': toolchain, 'delivery_artifact_toolchain': art['toolchain'], 'original_pytest_FAIL': 'reports/P3/final-check-pytest.json',
              'runtime_or_delivery_rebuild_requested': False, 'benchmark_build_or_execution': False,
              'FULL_queries': 0, 'retries': 0}
    if rec['exit'] == 0:
        verify_artifacts(art)
        after = {k: binding(art[k]['path']) for k in ('binary', 'wheel')}
        if before != after or sources != {'example': binding(source), 'runtime': binding(runtime)}:
            raise ValueError('delivery/source bytes changed while supplying fixture')
        result.update(status='PASS', probe=binding(probe), after=after,
                      delivery_artifacts_unchanged=True)
    create_new(out, result)
    print(json.dumps({'status': result['status'], 'exit': rec['exit']}))
    return rec['exit']


if __name__ == '__main__':
    raise SystemExit(main())
