"""Visual selection must keep image identity and handle unavailable evidence."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from evo_diagram.agentic_system.verification_stage.critic.comparison import compare_rendered_diagrams
from evo_diagram.agentic_system.workflow import Text2DiagramWorkflow


@pytest.mark.parametrize("preference", ["1", "2", "tie"])
def test_visual_comparison_maps_anonymous_order_back_to_correct_artifact(tmp_path, preference):
    original = tmp_path / 'original.png'
    candidate = tmp_path / 'candidate.png'
    original.write_bytes(b'original-image')
    candidate.write_bytes(b'candidate-image')
    captured = []

    def invoke(messages):
        captured.extend(messages)
        return SimpleNamespace(content=json.dumps({
            'preference': preference, 'reason': 'The relationship labels have more space.',
        }))

    result = compare_rendered_diagrams(
        str(original), str(candidate), 'Source relationship', model=SimpleNamespace(invoke=invoke),
    )
    order = sorted({'original': original, 'candidate': candidate},
                   key=lambda key: hashlib.sha256((original if key == 'original' else candidate).read_bytes()).hexdigest())
    assert result['winner'] == ('tie' if preference == 'tie' else order[int(preference) - 1])
    assert result['display_order'] == order
    content = captured[1].content
    assert [part['text'] for part in content if part['type'] == 'text'] == [
        'Source content:\nSource relationship', 'Image 1:', 'Image 2:',
    ]
    assert len([part for part in content if part['type'] == 'image_url']) == 2


def test_identical_render_skips_model_call(tmp_path):
    path = tmp_path / 'identical.png'
    path.write_bytes(b'same-image')
    result = compare_rendered_diagrams(str(path), str(path), 'source', model=object())
    assert result['winner'] == 'tie'
    assert result['display_order'] == []


@pytest.mark.parametrize('response', [
    '', '[]', '{"preference":"candidate","reason":"better"}',
    '{"preference":"2","reason":""}',
])
def test_invalid_comparison_is_not_treated_as_visual_improvement(tmp_path, response):
    original, candidate = tmp_path / 'a.png', tmp_path / 'b.png'
    original.write_bytes(b'a')
    candidate.write_bytes(b'b')
    model = SimpleNamespace(invoke=lambda _: SimpleNamespace(content=response))
    with pytest.raises(ValueError):
        compare_rendered_diagrams(str(original), str(candidate), 'source', model=model)


def test_production_selection_does_not_call_a_third_critic(monkeypatch):
    from evo_diagram.agentic_system.verification_stage.critic import comparison
    from evo_diagram.agentic_system.workflow import _refinement_regression_reason
    monkeypatch.setattr(comparison, 'compare_rendered_diagrams', lambda *args: pytest.fail('No third model call'))
    initial = SimpleNamespace(objective_summary={}, critique=SimpleNamespace(overall_score=8.5))
    candidate = SimpleNamespace(objective_summary={}, critique=SimpleNamespace(overall_score=8.6))
    assert _refinement_regression_reason(initial, candidate) is None
    candidate.critique.overall_score = 7.0
    assert _refinement_regression_reason(initial, candidate) is not None
