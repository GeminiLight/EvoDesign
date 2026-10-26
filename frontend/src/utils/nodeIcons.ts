import iconCatalog from '../../../evo_diagram/agentic_system/common/assets/material_icons.json';

export const NODE_ICON_SIZE = 26;
const PADDING = 16;
const GAP = 10;
const ICON_KEY = 'evoDesignIcon';
export const nodeIconNames = Object.keys(iconCatalog);
const catalog: Record<string, string> = iconCatalog;

export interface IconSceneElement {
  id: string;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  angle?: number;
  strokeColor?: string;
  version?: number;
  isDeleted?: boolean;
  groupIds?: readonly string[];
  containerId?: string | null;
  fileId?: string | null;
  customData?: Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface IconAsset {
  id: string;
  mimeType: 'image/svg+xml';
  dataURL: string;
  created: number;
  lastRetrieved: number;
}

export function getNodeIcon(element: IconSceneElement): { name: string; hostId: string } | null {
  const value = element.customData?.[ICON_KEY];
  if (element.type !== 'image' || !value || typeof value !== 'object') return null;
  const data = value as { name?: unknown; hostId?: unknown };
  return typeof data.name === 'string' && typeof data.hostId === 'string'
    ? { name: data.name, hostId: data.hostId } : null;
}

export function getIconHost(icon: IconSceneElement, elements: readonly IconSceneElement[]) {
  const data = getNodeIcon(icon);
  if (!data) return undefined;
  const hosts = elements.filter(e => ['rectangle', 'ellipse'].includes(e.type) && !e.is_group);
  const innerGroup = icon.groupIds?.[0];
  const grouped = innerGroup ? hosts.filter(e => e.groupIds?.includes(innerGroup)) : [];
  return grouped.length === 1 ? grouped[0] : hosts.find(e => e.id === data.hostId);
}

export function makeNodeIconAsset(name: string, stroke: string): IconAsset | null {
  if (!Object.hasOwn(catalog, name)) return null;
  const color = /^#[\da-f]{6}$/i.test(stroke) ? stroke : '#475569';
  const svg = catalog[name].replace('<svg ', `<svg fill="${color}" `)
    .replace(/(fill|stroke)="(?!none"|transparent")[^"]*"/g, `$1="${color}"`);
  return {
    id: `evodesign-icon-${name}-${color.slice(1).toLowerCase()}`,
    mimeType: 'image/svg+xml', dataURL: `data:image/svg+xml;base64,${btoa(svg)}`,
    created: 1, lastRetrieved: 1,
  };
}

/** Repair only explicitly marked node companions. Never move arbitrary images. */
export function reconcileNodeIcons(
  source: readonly IconSceneElement[],
  existingFiles: Record<string, unknown>,
): { elements: IconSceneElement[]; assets: IconAsset[]; changed: boolean } {
  const elements = source.map(e => ({ ...e }));
  const assets = new Map<string, IconAsset>();
  let changed = false;
  const update = (element: IconSceneElement, patch: Partial<IconSceneElement>) => {
    const differs = Object.entries(patch).some(([key, value]) => (
      typeof value === 'number' && typeof element[key] === 'number'
        ? Math.abs(value - (element[key] as number)) > 0.01
        : JSON.stringify(element[key]) !== JSON.stringify(value)
    ));
    if (!differs) return;
    Object.assign(element, patch, {
      version: (element.version ?? 1) + 1,
      versionNonce: Math.floor(Math.random() * 0x7fffffff),
      updated: Date.now(),
    });
    changed = true;
  };
  for (const icon of elements) {
    const data = getNodeIcon(icon);
    if (!data) continue;
    const host = getIconHost(icon, elements);
    if (!host) continue;
    if (icon.isDeleted) {
      const anotherIcon = elements.some(e => !e.isDeleted && getNodeIcon(e) && getIconHost(e, elements)?.id === host.id);
      const label = elements.find(e => e.type === 'text' && e.containerId === host.id && !e.isDeleted);
      if (!host.isDeleted && !anotherIcon && label) {
        update(label, { x: host.x + (host.width - label.width) / 2, y: host.y + (host.height - label.height) / 2, angle: host.angle ?? 0 });
      }
      continue;
    }
    if (host.isDeleted) {
      update(icon, { isDeleted: true });
      continue;
    }
    const text = elements.find(e => e.type === 'text' && e.containerId === host.id && !e.isDeleted);
    const size = Math.min(NODE_ICON_SIZE, Math.max(12, host.height - 16));
    const insetScale = host.type === 'ellipse' ? Math.SQRT2 : 1;
    if (text) {
      update(host, {
        width: Math.max(host.width, insetScale * (PADDING * 2 + size + GAP + text.width)),
        height: Math.max(host.height, insetScale * (text.height + 16), insetScale * (size + 16)),
      });
    }
    const { x, y, width, height } = host;
    const angle = host.angle ?? 0;
    const place = (element: IconSceneElement, cx: number, cy: number, w: number, h: number) => {
      const dx = cx - (x + width / 2), dy = cy - (y + height / 2);
      update(element, {
        x: x + width / 2 + dx * Math.cos(angle) - dy * Math.sin(angle) - w / 2,
        y: y + height / 2 + dx * Math.sin(angle) + dy * Math.cos(angle) - h / 2,
        width: w, height: h, angle,
      });
    };
    const padding = PADDING + width * (1 - 1 / insetScale) / 2;
    place(icon, x + padding + size / 2, y + height / 2, size, size);
    if (text) {
      const left = x + padding + size + GAP, right = x + width - padding;
      place(text, (left + right) / 2, y + height / 2, text.width, text.height);
    }
    update(icon, { customData: { ...icon.customData, [ICON_KEY]: { ...data, hostId: host.id } } });
    // Recolor only after an actual host style change or a user replacement.
    // Original embedded assets remain usable with no network or catalog access.
    const sourceHost = source.find(e => e.id === host.id);
    const asset = makeNodeIconAsset(data.name, sourceHost?.strokeColor ?? '#475569');
    if (asset && (icon.fileId !== asset.id || !existingFiles[asset.id])) {
      if (!existingFiles[asset.id]) {
        assets.set(asset.id, asset);
        changed = true;
      }
      update(icon, { fileId: asset.id });
    }
  }
  return { elements, assets: [...assets.values()], changed };
}
