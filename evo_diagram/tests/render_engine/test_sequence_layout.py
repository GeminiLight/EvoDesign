from copy import deepcopy

import pytest

from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import add_excalidraw_arrows_to_manifest, rebuild_excalidraw_arrows
from evo_diagram.agentic_system.render_engine.excalidraw.converter import InstantiationToExcalidrawConverter
from evo_diagram.agentic_system.verification_stage.checks.aggregator import run_all_checks
from evo_diagram.agentic_system.verification_stage.checks.sequence import check_sequence


@pytest.fixture
def sequence_scene():
    structure = {'chart_type': 'sequence_diagram', 'nodes': [
        {'id': name, 'label': name.upper(), 'class': 'actor', 'actor_id': name} for name in ('a', 'b', 'c')],
        'groups': [], 'edges': [
            {'id': 'edge:a2b', 'source': 'a', 'target': 'b', 'label': 'Submit', 'sequence_idx': 0},
            {'id': 'edge:b2c', 'source': 'b', 'target': 'c', 'label': 'Save', 'sequence_idx': 1},
            {'id': 'edge:c2b', 'source': 'c', 'target': 'b', 'label': 'Saved', 'sequence_idx': 2, 'message_kind': 'return'},
            {'id': 'edge:a2b_1', 'source': 'a', 'target': 'b', 'label': 'Poll', 'sequence_idx': 3},
            {'id': 'edge:b2b', 'source': 'b', 'target': 'b', 'label': 'Verify', 'sequence_idx': 4},
        ]}
    layout = {name: {'shape': 'rectangle', 'x': 100 + i * 240, 'y': 100, 'w': 160, 'h': 64}
              for i, name in enumerate(('a', 'b', 'c'))}
    for edge in structure['edges']:
        layout[edge['id']] = {'start': {'elementId': edge['source'], 'side': 'right'},
                              'end': {'elementId': edge['target'], 'side': 'left'}}
    scene = InstantiationToExcalidrawConverter(layout_instantiation=layout, structure_instantiation=structure).convert()
    return scene, structure, layout


def test_sequence_routes_messages_in_order_with_lifelines_returns_and_self_calls(sequence_scene):
    scene, structure, layout = sequence_scene
    result = add_excalidraw_arrows_to_manifest(scene, structure)
    assert not check_sequence(result, structure)
    assert not [finding for finding in run_all_checks(result, structure, layout)
                if finding.severity.value in {'major', 'critical', 'minor'}]
    lines = [e for e in result['elements'] if e['type'] == 'line']
    assert len(lines) == 3
    arrows = [e for e in result['elements'] if e['type'] == 'arrow']
    assert len(arrows) == 5
    assert arrows[2]['strokeStyle'] == 'dashed'
    assert len(arrows[-1]['points']) == 4
    assert len([e for e in result['elements'] if e.get('text') == 'Poll']) == 1
    # Rebuilding after a refinement edit must not duplicate or reorder messages.
    result['elements'][0]['x'] += 25
    rebuilt = rebuild_excalidraw_arrows(result, structure)
    assert not check_sequence(rebuilt, structure)
    assert len([e for e in rebuilt['elements'] if e['type'] == 'arrow']) == 5
    assert len([e for e in rebuilt['elements'] if e['type'] == 'line']) == 3


@pytest.mark.parametrize('corruption', ['order', 'horizontal', 'direction', 'return_style', 'lifeline'])
def test_sequence_quality_guard_rejects_visual_semantic_regressions(sequence_scene, corruption):
    scene, structure, _ = sequence_scene
    result = add_excalidraw_arrows_to_manifest(scene, structure)
    arrows = [e for e in result['elements'] if e['type'] == 'arrow']
    if corruption == 'order':
        arrows[1]['y'] = arrows[0]['y']
    elif corruption == 'horizontal':
        arrows[0]['points'][-1][1] = 100
    elif corruption == 'direction':
        arrows[0]['points'].reverse()
    elif corruption == 'return_style':
        arrows[2]['strokeStyle'] = 'solid'
    else:
        result['elements'] = [e for e in result['elements'] if e['type'] != 'line']
    assert check_sequence(result, structure)


def test_sequence_rebuild_is_idempotent(sequence_scene):
    scene, structure, _ = sequence_scene
    first = add_excalidraw_arrows_to_manifest(scene, structure)
    second = add_excalidraw_arrows_to_manifest(first, structure)
    assert second == first


def test_sequence_inputs_are_not_mutated(sequence_scene):
    scene, structure, _ = sequence_scene
    original = deepcopy(scene)
    add_excalidraw_arrows_to_manifest(scene, structure)
    assert original == scene


@pytest.mark.parametrize('icons', [False, True])
@pytest.mark.parametrize('group_surface', ['background', 'bare', 'both'])
def test_sequence_layout_workflow_needs_no_coordinate_model_call(sequence_scene, icons, group_surface):
    from evo_diagram.agentic_system.generation_stage.layout.workflow import LayoutWorkflow
    from evo_diagram.agentic_system.generation_stage.layout.layout_agent import LayoutAgent
    from evo_diagram.agentic_system.generation_stage.layout.state import WorkflowState
    _, structure, _ = sequence_scene
    structure['groups'] = [{'id': 'lane_a', 'members': ['a'], 'label': 'A'}]
    styling = {node['id']: {'shape': 'rectangle', 'label': {'text': node['label']},
                           'strokeColor': '#123456', 'backgroundColor': '#FFFFFF'} for node in structure['nodes']}
    styling.update({edge['id']: {'strokeColor': '#123456'} for edge in structure['edges']})
    styling['lane_a:background'] = {'shape': 'rectangle', 'strokeColor': '#123456', 'backgroundColor': 'transparent'}
    if group_surface in {'bare', 'both'}:
        styling['lane_a'] = {'shape': 'rectangle', 'label': {'text': 'A'},
                            'strokeColor': '#123456', 'backgroundColor': '#FFFFFF'}
        if group_surface == 'bare':
            del styling['lane_a:background']
    if icons:
        styling['a:icon'] = {'type': 'icon', 'props': {'icon': 'person'}}
    workflow = object.__new__(LayoutWorkflow)
    workflow.layout_agent = object.__new__(LayoutAgent)
    workflow.layout_agent.run = lambda *_: pytest.fail('Sequence coordinates must not call a model')
    state = WorkflowState(structure_instantiation=structure, styling_instantiation=styling)
    state = workflow._run_layout(workflow._run_estimate_sizes(state))
    assert state.layout_specification['strategy'] == 'deterministic_sequence'
    scene = InstantiationToExcalidrawConverter(state.layout_instantiation, structure).convert()
    result = add_excalidraw_arrows_to_manifest(scene, structure)
    assert not check_sequence(result, structure)
    assert not [f for f in run_all_checks(result, structure, state.layout_instantiation)
                if f.severity.value in {'critical', 'major', 'minor'}]
    visible_labels = [e for e in result['elements'] if e.get('type') == 'text'
                      and e.get('opacity', 100) > 0 and e.get('text') == 'A']
    assert len(visible_labels) == 1
    assert len([e for e in result['elements'] if e['type'] == 'image']) == int(icons)
    assert len([e for e in result['elements'] if e['type'] == 'arrow']) == 5


def test_refiner_repairs_sequence_order_without_breaking_returns_or_recoloring(sequence_scene):
    from evo_diagram.agentic_system.iterative_workflow import _apply_edit_batch
    from evo_diagram.agentic_system.refinement_stage.state import VerifierRefinerState, IterationLog
    scene, structure, layout = sequence_scene
    result = add_excalidraw_arrows_to_manifest(scene, structure)
    arrows = [e for e in result['elements'] if e['type'] == 'arrow']
    arrows[1]['y'] = arrows[0]['y']
    arrows[2]['strokeStyle'] = 'solid'
    arrows[2]['strokeColor'] = '#123456'
    assert check_sequence(result, structure)
    state = VerifierRefinerState(manifest_path='unused', image_path='unused', manifest=result,
                                structure=structure, layout_instantiation=layout)
    log = IterationLog(iteration=1)
    _apply_edit_batch(state, [], log=log, target_attr='deterministic_edits', log_prefix='test')
    assert not check_sequence(state.manifest, structure)
    fixed = [e for e in state.manifest['elements'] if e['type'] == 'arrow'][2]
    assert fixed['strokeStyle'] == 'dashed'
    assert fixed['strokeColor'] == '#123456'
    assert log.rerouted_arrows
