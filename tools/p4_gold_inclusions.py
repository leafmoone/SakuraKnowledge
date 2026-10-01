"""Export frozen gold's guaranteed pilot inclusions without database or models."""
import argparse
import hashlib
import json
from pathlib import Path

FROZEN_SHA = 'ae6fcc98021de5f5b4c905b5f35a438c6670005327e0276fd751d9cffe4635ba'


def inclusions(raw):
    if hashlib.sha256(raw).hexdigest() != FROZEN_SHA:
        raise ValueError('frozen gold SHA mismatch')
    gold = json.loads(raw)
    if gold['status'] != 'FROZEN_PRE_EMBEDDING':
        raise ValueError('gold not frozen')
    records = {}
    reasons = {}
    for case in gold['cases']:
        for anchor in case['accepted_targets']:
            did = anchor['document_id']
            item = {'document_id': did, 'entry_key': anchor['entry_key'],
                    'role': 'gold_target'}
            if did in records and records[did] != item:
                raise ValueError('conflicting target key')
            records[did] = item
            reasons.setdefault(did, set()).add('gold_target:' + case['case_id'])
    for item in gold['candidate_hard_negatives']:
        did, anchor = item['document_id'], item['anchor']
        if did in records and records[did]['entry_key'] != anchor['entry_key']:
            raise ValueError('conflicting hard-negative key')
        records.setdefault(did, {'document_id': did, 'entry_key': anchor['entry_key'],
                                 'role': 'hard_negative'})
        reasons.setdefault(did, set()).add('candidate_hard_negative:' + item['inspection_reason'])
    for case in gold['cases']:
        for did in case['candidate_hard_negative_document_ids']:
            if did not in records:
                raise ValueError('unanchored hard negative')
            reasons[did].add('candidate_hard_negative:' + case['case_id'])
    return [{**records[did], 'reason': '; '.join(sorted(reasons[did]))}
            for did in sorted(records)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gold', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    items = inclusions(args.gold.read_bytes())
    raw = (json.dumps(items, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    with args.output.open('xb') as out:
        out.write(raw)
    print(json.dumps({'gold_sha256': FROZEN_SHA, 'guaranteed_documents': len(items),
                      'inclusions_sha256': hashlib.sha256(raw).hexdigest()}))


if __name__ == '__main__':
    main()
