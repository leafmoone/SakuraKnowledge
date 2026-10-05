"""Run the frozen120 once against modular resident; preserve raw response streams."""
import argparse
import json
import os
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from tools import p4_existing_assets_evaluate as evaluation
from tools import p4_retrieval_metrics as metrics
from tools.p4_rust_pilot import Driver
from tools.portable_validate import _summary


def closure(response, connections):
    for candidate in response['candidates']:
        key = candidate.get('entry', candidate.get('entry_key'))
        found = False
        for name in candidate['source_packs']:
            c = connections[name]
            found |= bool(c.execute("SELECT 1 FROM entries e WHERE kind=? AND namespace=? AND value=? AND conflicted=0 AND EXISTS(SELECT 1 FROM entry_evidence v JOIN sources s ON s.source_id=v.source_id WHERE v.entry_id=e.id AND v.status='source_backed')", (key['kind'], key['namespace'], key['value'])).fetchone())
        if not found:
            raise ValueError('candidate has no selected source-backed identity')
    for field in ('documents', 'evidence', 'citations', 'trusted_pins', 'lexical_hits', 'dense_hits'):
        for record in response.get(field, []):
            sid, eid = record.get('source_id'), record.get('evidence_id')
            if not sid or not eid:
                continue
            names = record.get('source_packs', list(connections))
            valid = False
            for n in names:
                c=connections[n]
                if not c.execute('SELECT 1 FROM sources WHERE source_id=?',(sid,)).fetchone():
                    continue
                did=record.get('document_id')
                if did is not None:
                    row=c.execute('SELECT d.source_id,d.evidence_id,d.status,e.kind,e.namespace,e.value FROM documents d JOIN entries e ON e.id=d.entry_id WHERE d.id=?',(int(did),)).fetchone()
                    k=record.get('entry_key',record.get('entry'))
                    valid = bool(row and row[0]==sid and row[1]==eid and row[2] in ('source_backed','generated_from_evidence') and (not k or tuple(row[3:])==(k['kind'],k['namespace'],k['value'])))
                else:
                    k=record.get('entry_key',record.get('entry'))
                    if not k:
                        keys=[x.get('entry',x.get('entry_key')) for x in response['candidates'] if n in x.get('source_packs',[]) and any(y.get('source_id')==sid and y.get('evidence_id')==eid for y in x.get('citations',[]))]
                        for candidate_key in keys:
                            entry=c.execute('SELECT id FROM entries WHERE kind=? AND namespace=? AND value=?',(candidate_key['kind'],candidate_key['namespace'],candidate_key['value'])).fetchone()
                            if entry and c.execute('SELECT 1 FROM entry_evidence WHERE entry_id=? AND source_id=? AND evidence_id=? AND status=\'source_backed\'',(entry[0],sid,eid)).fetchone():
                                valid=True
                                break
                    if k:
                        row=c.execute('SELECT id FROM entries WHERE kind=? AND namespace=? AND value=?',(k['kind'],k['namespace'],k['value'])).fetchone()
                        if row:
                            valid=bool(c.execute('SELECT 1 FROM entry_evidence WHERE entry_id=? AND source_id=? AND evidence_id=? AND status=\'source_backed\' UNION ALL SELECT 1 FROM aliases WHERE entry_id=? AND source_id=? AND evidence_id=? AND status=\'source_backed\'',(row[0],sid,eid,row[0],sid,eid)).fetchone())
                if valid:
                    break
            if not valid:
                raise ValueError('source/evidence/typed document closure missing')


def run(root, output):
    root, output = Path(root), Path(output)
    connections = {p.parent.name: sqlite3.connect((p.parent/'knowledge.sqlite').resolve().as_uri()+'?mode=ro', uri=True) for p in (root/'packs').glob('*/manifest.json')}
    cases = json.loads((evaluation.ROOT/evaluation.GOLD).read_bytes())['cases']
    report = {'schema': 'sakura-modular-semantic120-v1', 'cases': [], 'status': 'FAIL'}
    raw_responses = []
    with output.with_suffix('.stderr').open('wb') as stderr, output.with_suffix('.jsonl').open('wb') as raw:
        previous = os.environ.get('PATH', '')
        os.environ['PATH'] = 'C:/Windows/System32;C:/Windows'
        started = time.perf_counter()
        try:
            child = Driver([str(root/'bin/semantic_pilot.exe'), '--config', str(root/'sknow-config.json')], stderr)
        finally:
            os.environ['PATH'] = previous
        opened, _ = child.receive(180)
        report['opened'], report['startup_ms'] = opened, (time.perf_counter()-started)*1000
        try:
            for case in cases:
                start = time.perf_counter()
                response, size = child.request(case)
                wall = (time.perf_counter()-start)*1000
                raw.write(child.last_raw)
                raw.flush()
                validation_start=time.perf_counter()
                closure(response, connections)
                validation_ms=(time.perf_counter()-validation_start)*1000
                if response['status'] != 'PASS' or wall > 5000 or size > 1048576:
                    raise ValueError('runtime/byte/wall failure')
                if response['timings_ms']['query_encodings'] != 1:
                    raise ValueError('query was not encoded exactly once')
                targets = [metrics.EntryKey(**t['entry_key']) for t in case['accepted_targets']]
                scores = {}
                for label, field in [('lexical', 'lexical_hits'), ('dense', 'dense_hits'), ('final', 'candidates')]:
                    ranking = [metrics.EntryKey(**r.get('entry', r.get('entry_key'))) for r in response[field]]
                    scores[label] = asdict(metrics.evaluate_case(case['case_id'], evaluation.subset(case), ranking, targets))
                report['cases'].append({'case_id': case['case_id'], 'status': 'PASS', 'wall_ms': wall, 'response_bytes': size, 'scores': scores, 'timings_ms': response['timings_ms'], 'pack_timings_ms': response['pack_timings_ms'], 'source_closure': 'PASS', 'validation_ms': validation_ms})
                raw_responses.append(response)
            report['status'] = 'PASS'
        except (ValueError, KeyError, TypeError, RuntimeError, OSError, sqlite3.Error) as error:
            report['error'] = repr(error)
        finally:
            report['shutdown'] = child.close(terminal=report['status'] != 'PASS')
    report['wall_ms'] = _summary([r['wall_ms'] for r in report['cases']])
    report['response_bytes'] = _summary([r['response_bytes'] for r in report['cases']])
    for c in connections.values():
        c.close()
    output.with_suffix('.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'cases': len(report['cases']), 'error': report.get('error'), 'startup_ms': report['startup_ms'], 'wall_ms': report['wall_ms']}))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    run(a.root, a.output)
