"""Tiny saved-branch replay: no search or encoding."""
from dataclasses import asdict

from tests.test_p4_saved_results_analysis import fixture
from tools import p4_existing_assets_evaluate as replay
from tools.p4_ef_replay import replay_dense


def test_same_dense_preserves_scores_and_changed_dense_preserves_pins():
    case, original, manifest = fixture(['target'], ['other'], ['target'], ['pin'])
    entities = [{'entry': original['dense_hits'][0]['entry'], 'entity_rank': 1}]
    assert replay_dense(case, original, entities, manifest) == replay.score_response(case, original, manifest)
    entities = [{'entry': original['lexical_hits'][0]['entry'], 'entity_rank': 1}]
    changed = replay_dense(case, original, entities, manifest)
    assert changed['final'].metrics.recall_at_10 == 1
    assert changed['lexical'] == replay.score_response(case, original, manifest)['lexical']
    assert asdict(changed['final'])['identity_promotion_error'] is False
