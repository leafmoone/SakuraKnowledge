"""Small cosine/rank/mapping fixtures; no large assets."""
import json
import sqlite3

import numpy as np
import pytest

from tools.p4_targeted_exact import compare_ann, cosine, map_entities, scan_cos


def test_real_cosine_nonunit_norms_ties_and_shared_block_rank():
    vectors = np.array([[2, 0], [1, 0], [0, 8], [-3, 0]], dtype=np.float32)
    queries = np.array([[7, 0], [0, 4]], dtype=np.float64)
    assert cosine(vectors, queries).tolist() == [[1, 0], [1, 0], [0, 1], [-1, 0]]
    top, ranks, _ = scan_cos(vectors, queries, [[1], [2]], depth=2, block_size=1)
    assert top[0][0].tolist() == [0, 1]
    assert ranks[0][0]['global_rank'] == 2
    assert ranks[0][0]['near_rank_interval'] == [1, 2]
    assert ranks[1][0]['global_rank'] == 1


@pytest.mark.parametrize('vectors', [np.empty((0, 2)), np.array([[0., 0.]]), np.array([[np.nan, 1.]])])
def test_empty_zero_nonfinite_rejected(vectors):
    with pytest.raises(ValueError):
        scan_cos(vectors, np.array([[1., 0.]]), [[]])


def test_positions_and_mapping_entity_cap():
    with pytest.raises(ValueError, match='position'):
        scan_cos(np.ones((2, 2)), np.ones((1, 2)), [[1, 1]])
    connection = sqlite3.connect(':memory:')
    connection.execute('CREATE TABLE chunks(position INTEGER PRIMARY KEY,metadata TEXT)')
    for p, value in enumerate(['a', 'a', 'b']):
        connection.execute('INSERT INTO chunks VALUES(?,?)', (p, json.dumps({'entry_key': {
            'kind': 'subject', 'namespace': 'source', 'value': value}, 'document_id': p, 'chunk_id': f'c{p}'})))
    chunks, entities = map_entities(connection, [0, 1, 2], [.9, .8, .7], limit=1)
    assert len(chunks) == 3 and len(entities) == 1
    assert entities[0]['chunk_id'] == 'c0'
    with pytest.raises(ValueError, match='duplicate'):
        map_entities(connection, [0, 0], [.9, .8])
    with pytest.raises(ValueError, match='unmapped'):
        map_entities(connection, [5], [.9])
    row = {'case_id': 'tiny', 'exact_top512_chunks': chunks,
           'saved_ann_top100_entities': [{'entry': entities[0]['entry']}],
           'targets_all_entity_chunks': [{'entry': entities[0]['entry'], 'position': 0,
                                         'exact_entity_rank': 1, 'exact_in_top512': True}],
           'classification': 'E'}
    compare_ann({'cases': [row]}, {'open_ms': 0, 'cases': [{'case_id': 'tiny', 'positions': [2],
                  'distances': [.3], 'search_ms': 1}]}, connection)
    assert row['classification'] == 'E'  # New entities differ: no historical attribution.
    assert row['new_ann_probe']['saved_entity_order_matches'] is False
    connection.close()
