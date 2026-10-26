"""Missing requested icons can be repaired without losing source content."""
import copy
import json
import pytest
from evo_diagram.agentic_system.render_engine.excalidraw.converter import InstantiationToExcalidrawConverter
from evo_diagram.agentic_system.refinement_stage.fixers.apply_edits import apply_edits
from evo_diagram.agentic_system.refinement_stage.state import EditOp
from evo_diagram.agentic_system.common.node_icons import ICON_KEY
from evo_diagram.agentic_system.verification_stage.checks.node_icons import check_node_icons
from evo_diagram.agentic_system.refinement_stage.agent.prompts import build_refiner_user_prompt
from evo_diagram.agentic_system.iterative_workflow import _touched_geometry_ids


def scene():
    return InstantiationToExcalidrawConverter({'n': {'shape': 'rectangle', 'x': 100, 'y': 100,
        'w': 130, 'h': 64, 'strokeColor': '#234567', 'label': {'text': 'Investigate'}}}).convert()


def test_missing_icon_repair_keeps_label_and_native_ownership_and_is_idempotent():
    manifest = scene(); node = next(e for e in manifest['elements'] if e['type'] == 'rectangle')
    text = next(e for e in manifest['elements'] if e['type'] == 'text')
    before_text = text['text']; width = node['width']
    edit = EditOp(op='set_icon', id=node['id'], payload={'name': 'analytics'}, source='llm')
    _, outcomes = apply_edits(manifest, [edit])
    assert outcomes[0].applied and _touched_geometry_ids(outcomes) == {node['id']}
    icon = next(e for e in manifest['elements'] if e['type'] == 'image')
    assert icon['customData'][ICON_KEY]['hostId'] == node['id']
    assert node['groupIds'] == icon['groupIds'] == text['groupIds']
    assert text['text'] == before_text and text['containerId'] == node['id']
    assert node['width'] >= width and icon['width'] == 26
    assert check_node_icons(json.loads(json.dumps(manifest)), 'excalidraw') == []
    before = copy.deepcopy(manifest)
    assert not apply_edits(manifest, [edit])[1][0].applied
    assert manifest == before
    assert apply_edits(manifest, [edit.model_copy(update={'payload': {'name': 'engineering'}})])[1][0].applied
    assert len([e for e in manifest['elements'] if e['type'] == 'image']) == 1


@pytest.mark.parametrize('bad', ['unknown', 'remote', 'group', 'diamond', 'locked'])
def test_icon_repair_rejects_unsafe_assets_or_hosts_without_mutation(bad):
    manifest = scene(); node = manifest['elements'][0]
    name = 'analytics'
    if bad == 'unknown': name = 'not_an_icon'
    if bad == 'remote': name = 'https://example.com/image.svg'
    if bad == 'group': node['is_group'] = True
    if bad == 'diamond': node['type'] = 'diamond'
    if bad == 'locked': node['locked'] = True
    before = copy.deepcopy(manifest)
    _, outcomes = apply_edits(manifest, [EditOp(op='set_icon', id=node['id'], payload={'name':name}, source='llm')])
    assert not outcomes[0].applied and outcomes[0].error
    assert manifest == before


def test_refiner_receives_exact_constraint_failure_before_optional_styling():
    violation = 'Investigate is missing its explicitly requested icon'
    prompt = build_refiner_user_prompt('flowchart', [], {
        'constraint_violations': [violation], 'styling': {'weaknesses': ['Minor color preference']}}, [])
    assert violation in prompt and prompt.index(violation) < prompt.index('Minor color preference')


def test_icon_repair_rolls_back_when_the_request_locks_the_host():
    from evo_diagram.agentic_system.iterative_workflow import _apply_edit_batch
    from evo_diagram.agentic_system.refinement_stage.state import IterationLog, VerifierRefinerState
    manifest = scene(); node = manifest['elements'][0]
    before = copy.deepcopy(manifest)
    state = VerifierRefinerState(manifest_path='unused.json', image_path='unused.png',
        manifest=manifest, design_constraints=json.dumps({'locked_element_ids': [node['id']]}))
    outcomes = _apply_edit_batch(state, [EditOp(op='set_icon', id=node['id'],
        payload={'name':'analytics'}, source='llm')], log=IterationLog(iteration=1),
        target_attr='llm_edits', log_prefix='test')
    assert not outcomes[0].applied and 'locked' in outcomes[0].error
    assert state.manifest == before


def test_icon_toggle_blocks_refiner_additions_even_when_the_model_requests_one():
    from evo_diagram.agentic_system.common.design_constraints import build_design_constraints
    from evo_diagram.agentic_system.iterative_workflow import _apply_edit_batch
    from evo_diagram.agentic_system.refinement_stage.state import IterationLog, VerifierRefinerState
    manifest = scene(); node = manifest['elements'][0]; before = copy.deepcopy(manifest)
    state = VerifierRefinerState(manifest_path='unused.json', image_path='unused.png',
        manifest=manifest, design_constraints=build_design_constraints(use_icons=False))
    outcomes = _apply_edit_batch(state, [EditOp(op='set_icon', id=node['id'],
        payload={'name':'analytics'}, source='llm')], log=IterationLog(iteration=1),
        target_attr='llm_edits', log_prefix='test')
    assert not outcomes[0].applied and 'disabled' in outcomes[0].error
    assert state.manifest == before
