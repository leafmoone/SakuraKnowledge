"""Tiny offline fusion attribution tests, without backend execution."""
from dataclasses import asdict

import pytest

from tools import p4_retrieval_metrics as metrics
from tools import p4_saved_results_analysis as analysis


def fixture(lexical, dense, targets, pins=()):
    def entry(value):
        return {'kind': 'subject', 'namespace': 'test.subject', 'value': value}
    def rows(values):
        return [{'entry': entry(v), 'rank': i} for i, v in enumerate(values, 1)]
    branches = {'lexical': rows(lexical), 'dense': rows(dense)}
    trusted = [{'entry': entry(v), 'match': 'alias', 'source_id': 'source', 'evidence_id': 'evidence'} for v in pins]
    fused = metrics.reciprocal_rank_fusion(
        {n: [metrics.Hit(analysis.key(r), r['rank']) for r in rows] for n, rows in branches.items()},
        [metrics.TrustedPin(analysis.key(p), p['match'], p['source_id'], p['evidence_id']) for p in trusted])
    result = {'status': 'PASS', 'case_id': 'tiny', 'query': 'query', 'contract': {}, 'pack_version': 'tiny',
              'identity_status': 'not_asserted', 'promoted_identities': [], 'canonical': None, 'entity_tag': None,
              'timings_ms': {'total': 1}, 'lexical_hits': branches['lexical'], 'dense_hits': branches['dense'],
              'trusted_pins': trusted, 'hybrid': [{'entry': asdict(c.entry)} for c in fused[:100]],
              'candidates': [{'entry': asdict(c.entry), 'hybrid_rank': c.hybrid_rank} for c in fused[:100]]}
    case = {'case_id': 'tiny', 'query': 'query', 'subset': 'semantic',
            'accepted_targets': [{'entry_key': entry(v), 'document_id': i} for i, v in enumerate(targets)]}
    return case, result, {'contract': {}, 'pack_version': 'tiny'}


def test_duplicates_keep_original_rrf_document_rank_and_all_targets():
    row, scored = analysis.analyze_case(*fixture(['a', 'a', 'target'], ['other'], ['target', 'missing']))
    target, missing = row['targets']
    assert target['lexical_document_ranks'] == [3]
    assert target['lexical_entity_rank'] == 2
    assert target['duplicates_before_first_lexical_hit'] == 1
    assert target['contribution']['branch_contributions']['lexical'] == 1 / 63
    assert missing['in_branch_union'] is False
    assert scored['lexical'].metrics.recall_at_10 == .5


def test_pins_are_preserved_but_negatives_remain_nonempty_without_promotion():
    row, scored = analysis.analyze_case(*fixture(['a'], ['b'], [], ['pin']))
    assert row['trusted_pins'][0]['source_id'] == 'source'
    assert scored['full'].returned_count == 3
    assert scored['full'].identity_promotion_error is False
    assert scored['full'].metrics.recall_at_10 is None


def test_boundary_loss_contributions_and_cap_are_not_union_absence():
    lexical = ['target'] + [f'a{i:03}' for i in range(1, 100)]
    dense = [f'a{i:03}' for i in range(1, 100)] + ['extra']
    row, _ = analysis.analyze_case(*fixture(lexical, dense, ['target']))
    trace = row['targets'][0]
    assert trace['lost_from_lexical_top10'] is True
    assert trace['in_branch_union'] is True
    assert len(trace['preceding_fused_candidates']) > 10
    assert trace['preceding_fused_candidates'][0]['branch_contributions']['dense'] == 1 / 61
    assert trace['displacing_top10'][0]['branch_ranks']['lexical'] > 10
    # A reconstruction mismatch is a hard failure, never silently rescored.
    case, response, manifest = fixture(['target'], ['a'], ['target'])
    response['candidates'].reverse()
    with pytest.raises(ValueError, match='fusion mismatch'):
        analysis.analyze_case(case, response, manifest)
