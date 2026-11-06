import { describe, expect, it } from 'vitest';
import { StylingAgent } from '../../src/generation_stage/styling/styling_agent.ts';
import { WorkflowState } from '../../src/generation_stage/styling/state.ts';
import { renderExcalidrawManifest } from '../../src/render_engine/workflow.ts';

const structure = {
  chart_type: 'architecture',
  nodes: [{ id: 'web', label: 'Web', role: 'client' }, { id: 'mysql', label: 'MySQL', role: 'database' }],
  edges: [{ id: 'edge:web2mysql', source: 'web', target: 'mysql' }], groups: [],
};

function styles() {
  return {
    web: { shape: 'rectangle', label: { text: 'Web' }, icon: 'outline_globe', strokeColor: '#3F7E8C', backgroundColor: '#D2E9EB' },
    mysql: { shape: 'rectangle', label: { text: 'MySQL' }, icon: 'outline_database', strokeColor: '#56765A', backgroundColor: '#D8E6D1' },
    'edge:web2mysql': { strokeColor: '#3F7E8C' },
  };
}

async function style(raw: Record<string, unknown>, enabled = true) {
  const agent = Object.create(StylingAgent.prototype) as StylingAgent;
  agent.use_icons = enabled;
  agent._system_prompt = 'system';
  agent.invoke_with_history = async () => ({ specification: {}, instantiation: raw });
  return (await agent.run(new WorkflowState({ structure_instantiation: structure }))).styling_instantiation! as Record<string, any>;
}

describe('model-authored top-level node icons', () => {
  it('reaches the rendered manifest as portable embedded SVGs', async () => {
    const raw = styles();
    const styled = await style(raw);
    const layout = { ...styled,
      web: { ...styled.web, x: 100, y: 100, w: 240, h: 100 },
      mysql: { ...styled.mysql, x: 500, y: 100, w: 240, h: 100 },
      'edge:web2mysql': { ...styled['edge:web2mysql'], start: { elementId: 'web', side: 'right' }, end: { elementId: 'mysql', side: 'left' } },
    };
    const manifest = renderExcalidrawManifest({ structure_instantiation: structure, layout_instantiation: layout }) as {
      elements: Record<string, any>[]; files: Record<string, { dataURL: string }>;
    };
    const icons = manifest.elements.filter(e => e.type === 'image');
    expect(icons).toHaveLength(2);
    expect(icons.map((e: any) => e.customData.evoDesignIcon.name).sort()).toEqual(['outline_database', 'outline_globe']);
    for (const icon of icons) {
      expect(manifest.files[icon.fileId].dataURL).toMatch(/^data:image\/svg\+xml;base64,/);
    }
    expect(styled.web).not.toHaveProperty('icon');
    expect(raw.web.icon).toBe('outline_globe');
  });

  it('enforces the unchecked icon option', async () => {
    const styled = await style(styles(), false);
    expect(Object.keys(styled).filter(k => k.endsWith(':icon'))).toEqual([]);
    expect(styled.web).not.toHaveProperty('icon');
  });

  it('preserves selective coverage', async () => {
    const raw: Record<string, any> = styles();
    delete raw.mysql.icon;
    const styled = await style(raw);
    expect(Object.keys(styled).filter(k => k.endsWith(':icon'))).toEqual(['web:icon']);
  });

  it.each([false, true])('preserves existing inline/canonical precedence (canonical=%s)', async canonical => {
    const raw: Record<string, any> = styles();
    raw.web.props = { icon: 'outline_smartphone' };
    if (canonical) raw['web:icon'] = { type: 'icon', props: { icon: 'outline_database' } };
    const styled = await style(raw);
    expect(styled['web:icon'].props.icon).toBe(canonical ? 'outline_database' : 'outline_smartphone');
    expect(styled.web.props).not.toHaveProperty('icon');
    expect(styled.web).not.toHaveProperty('icon');
    expect(raw.web.props.icon).toBe('outline_smartphone');
  });
});
