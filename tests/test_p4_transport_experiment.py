"""Narrow explicit experimental authority; no assets or real retrieval."""
import copy
import json

import pytest

from tools import p4_full_acceptance as acceptance
from tools import p4_full_preflight as full


def test_only_expected_width_diff_and_explicit_contract_binding():
    original = json.loads(full.FULL_CONTRACT.read_bytes())
    experiment = json.loads((full.ROOT / 'configs/p4-ef2048-transport-experiment.json').read_bytes())
    expected = copy.deepcopy(original)
    expected['declarative_contract']['ann']['expansion_search'] = 2048
    assert experiment == expected
    with pytest.raises(ValueError):
        full.validate_contract(experiment)
    assert full.validate_contract(experiment, expected_expansion_search=2048)['ann']['expansion_search'] == 2048
    for width in (True, 1024, 0, '2048'):
        with pytest.raises(ValueError):
            full.validate_contract(experiment, expected_expansion_search=width)
    altered = copy.deepcopy(experiment)
    altered['declarative_contract']['ann']['entry_depth'] = 101
    with pytest.raises(ValueError):
        full.validate_contract(altered, expected_expansion_search=2048)
    declaration, _, binding = acceptance._canonical(experiment, experimental_ef2048=True)
    assert declaration['ann']['expansion_search'] == 2048
    assert binding['path'] == 'configs/p4-ef2048-transport-experiment.json'
    assert acceptance.runtime_contract(declaration, 3)['ann']['expansion_search'] == 2048
