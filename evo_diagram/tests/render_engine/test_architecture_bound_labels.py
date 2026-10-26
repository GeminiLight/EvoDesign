"""Native arrow text must stay clear after editor restoration and export."""
from copy import deepcopy
import pytest

from evo_diagram.agentic_system.render_engine.excalidraw.arrow_adder import (
    _position_architecture_bound_labels, _segment_hits_box,
)


@pytest.mark.parametrize('group_frame', [False, True])
@pytest.mark.parametrize('single_segment', [False, True])
def test_short_midsegment_label_clears_foreign_edge_without_detaching(group_frame, single_segment):
    # A nearly vertical Consume return overlaps the outgoing Read assets path.
    arrows = [
        {'id': 'consume', 'type': 'arrow', 'elbowed': True, 'x': 681, 'y': 800,
         'points': [[0, 0], [0, -81], [2.5, -81], [2.5, -162]],
         'boundElements': [{'id': 'label', 'type': 'text'}]},
        {'id': 'assets', 'type': 'arrow', 'elbowed': True, 'x': 683.5, 'y': 638,
         'points': [[0, 0], [0, 81], [229.5, 81], [229.5, 162]]},
    ]
    if single_segment:
        arrows[0]['points'] = [[0, 0], [2.5, -162]]
        arrows[0]['elbowed'] = False
    label = {'id': 'label', 'type': 'text', 'containerId': 'consume', 'text': 'Consume',
             'width': 55, 'height': 16, 'x': 691, 'y': 695}
    nodes = [{'id': 'queue', 'type': 'rectangle', 'x': 600, 'y': 800, 'width': 162, 'height': 64},
             {'id': 'worker', 'type': 'rectangle', 'x': 600, 'y': 574, 'width': 167, 'height': 64}]
    ctx = {'consume': {'source_ref': 'queue', 'target_ref': 'worker', 'start_side': 'top', 'end_side': 'bottom', 'obstacles': [], 'source_bbox': {'x': 600, 'y': 800, 'w': 162, 'h': 64},
                       'target_bbox': {'x': 600, 'y': 574, 'w': 167, 'h': 64}}}
    ctx['assets'] = {'source_ref': 'worker', 'target_ref': 'store', 'start_side': 'bottom', 'end_side': 'top',
                     'obstacles': [], 'source_bbox': ctx['consume']['target_bbox'],
                     'target_bbox': {'x': 830, 'y': 800, 'w': 166, 'h': 64}}
    before = deepcopy(arrows)
    if group_frame:
        # Renderer frames are identified by semantic membership, not is_group.
        nodes.append({'id': 'processing', 'type': 'rectangle', 'x': 500, 'y': 550,
                      'width': 600, 'height': 195})
    _position_architecture_bound_labels(nodes, [*arrows, label], ctx,
                                        {'processing'} if group_frame else set())
    arrow = arrows[0]
    center = [arrow['x'] + (arrow['points'][1][0] + arrow['points'][2][0])/2,
              arrow['y'] + (arrow['points'][1][1] + arrow['points'][2][1])/2]
    assert [label['x']+label['width']/2, label['y']+label['height']/2] == center
    foreign = [(arrows[1]['x']+x, arrows[1]['y']+y) for x, y in arrows[1]['points']]
    assert not any(_segment_hits_box(a, b, (label['x']-6, label['y']-6, 67, 28))
                   for a, b in zip(foreign, foreign[1:]))
    assert label['containerId'] == 'consume'
    assert arrow['boundElements'] == before[0]['boundElements']
    assert arrow['points'][0] == before[0]['points'][0]
    assert arrow['y'] + arrow['points'][-1][1] == 638
    assert 600 < arrow['x'] + arrow['points'][-1][0] < 767
    assert arrows[1]['id'] == before[1]['id']
