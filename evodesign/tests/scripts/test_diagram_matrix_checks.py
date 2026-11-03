"""The smoke oracle must catch inverted conditions, not just graph topology."""
from copy import deepcopy

import pytest

from scripts.research.check_diagram_matrix import check


def sample():
    case = {'diagram_type': 'flowchart', 'labels': ['Valid?', 'Continue'],
            'edges': [['Valid?', 'Continue']],
            'branch_labels': [['Valid?', 'Continue', 'Yes']]}
    structure = {'nodes': [{'id': 'a', 'label': 'Valid?'}, {'id': 'b', 'label': 'Continue'}],
                 'edges': [{'id': 'edge:a2b', 'source': 'a', 'target': 'b', 'label': 'Yes'}]}
    scene = {'_meta': {'id_map': {'a': 'a', 'b': 'b'}}, 'elements': [
        {'id': 'a', 'type': 'diamond'}, {'id': 'b', 'type': 'rectangle'},
        {'id': 'a:text', 'type': 'text', 'text': 'Valid?'},
        {'id': 'b:text', 'type': 'text', 'text': 'Continue'},
        {'id': 'arrow', 'type': 'arrow', 'meta': {'semantic_edge_id': 'edge:a2b'}},
        {'id': 'label', 'type': 'text', 'text': 'Yes', 'containerId': 'arrow'},
    ]}
    return case, {'thought_trace': {'structure_instantiation': structure}, 'schema_blob': scene}


def test_expected_branch_is_accepted():
    case, result = sample()
    assert check(case, result, False)['passed']


@pytest.mark.parametrize('failure', ['semantic', 'rendered', 'missing'])
def test_inverted_or_missing_branch_is_rejected(failure):
    case, result = sample()
    result = deepcopy(result)
    if failure == 'semantic':
        result['thought_trace']['structure_instantiation']['edges'][0]['label'] = 'No'
    elif failure == 'rendered':
        result['schema_blob']['elements'][-1]['text'] = 'No'
    else:
        result['schema_blob']['elements'].pop()
    assert not check(case, result, False)['passed']
