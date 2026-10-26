import React, { useEffect, useState } from 'react'
import { Editor, useEditor, useValue } from 'tldraw'

/* -------------------- Constants & Types -------------------- */
const COLORS = ['black', 'grey', 'red', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink'] as const
type ColorName = typeof COLORS[number]

const STROKE_SIZES = ['s', 'm', 'l', 'xl'] as const
type SizeName = typeof STROKE_SIZES[number]

type Panel = 'none' | 'stroke' | 'fill' | 'shape'

const GAP = 12

type SelectionStylePatch = Partial<{
  color: ColorName
  size: SizeName
  dash: 'draw' | 'solid' | 'dashed'
  fill: 'none' | 'semi' | 'solid'
  rounding: number
  geo: 'rectangle' | 'ellipse' | 'triangle' | 'diamond'
}>

type ShapeWithProps = {
  id: string
  type: string
  props: Record<string, unknown>
}

const hasShapeProps = (shape: unknown): shape is ShapeWithProps => {
  return Boolean(
    shape
    && typeof shape === 'object'
    && 'id' in shape
    && 'type' in shape
    && 'props' in shape
    && typeof (shape as { props?: unknown }).props === 'object'
    && (shape as { props?: unknown }).props !== null,
  )
}

/* -------------------- Helper Functions -------------------- */

/**
 * Updates the style properties of the currently selected shapes.
 */
function patchSelectionStyles(
  editor: Editor,
  patch: SelectionStylePatch
) {
  const ids = editor.getSelectedShapeIds()
  if (!ids.length) return

  type ShapeUpdate = Parameters<Editor['updateShapes']>[0][number]
  const updates: Parameters<Editor['updateShapes']>[0] = ids
    .map((id) => {
      const shape = editor.getShape(id)
      if (!shape) return null

      // This works specifically for 'geo' shapes in tldraw
      if (patch.geo && shape.type !== 'geo') return null
      if (!hasShapeProps(shape)) return null

      const propsPatch: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(patch)) {
        if (v !== undefined && k in shape.props) {
          propsPatch[k] = v
        }
      }

      if (Object.keys(propsPatch).length > 0) {
        return { id: shape.id, type: shape.type, props: propsPatch } as ShapeUpdate
      }
      return null
    })
    .filter(Boolean) as Parameters<Editor['updateShapes']>[0]

  if (updates.length > 0) editor.updateShapes(updates)
}

/**
 * A hook to get the anchor point (top-center) of the current selection in page coordinates.
 */
function useSelectionAnchor(editor: Editor | null) {
  return useValue(
    'selection-anchor',
    () => {
      if (!editor) return null

      const bounds = editor.getSelectionRotatedPageBounds() ?? editor.getSelectionPageBounds()
      if (!bounds) return null

      return { x: bounds.center.x, y: bounds.minY }
    },
    [editor]
  )
}

/* -------------------- UI Components & Styles -------------------- */

const IconBtn: React.FC<
  React.PropsWithChildren<{ title?: string; onClick?: () => void; active?: boolean }>
> = ({ children, title, onClick, active }) => (
  <button
    title={title}
    onClick={onClick}
    className={`
      w-8 h-8 flex items-center justify-center rounded-lg transition-all duration-200
      ${active
        ? 'bg-blue-50 text-blue-600 ring-1 ring-blue-200'
        : 'text-slate-500 hover:bg-slate-100 hover:text-slate-700'
      }
    `}
  >
    {children}
  </button>
)

const PaletteIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" stroke="none"/>
    <circle cx="17.5" cy="10.5" r=".5" fill="currentColor" stroke="none"/>
    <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" stroke="none"/>
    <circle cx="6.5" cy="12.5" r=".5" fill="currentColor" stroke="none"/>
    <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
  </svg>
)

const StrokeIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M12 2v20" />
    <path d="M2 12h20" />
  </svg>
)

const ShapeIcon = () => (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
        <circle cx="8.5" cy="8.5" r="1.5" />
        <path d="M21 15l-5-5L5 21" />
    </svg>
)

const FadeCard: React.FC<
  React.PropsWithChildren<{
    anchorX: number
    anchorY: number
    zoom: number
    className?: string
  }>
> = ({ children, anchorX, anchorY, zoom, className }) => {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const id = requestAnimationFrame(() => setOpen(true))
    return () => cancelAnimationFrame(id)
  }, [])

  const scale = 1 / zoom

  return (
    <div
      className={`absolute flex flex-col items-center ${className}`}
      style={{
        zIndex: 2147483647,
        left: anchorX,
        top: anchorY,
        transform: open
          ? `translate(-50%, calc(-100% - ${GAP / zoom}px)) scale(${scale})`
          : `translate(-50%, calc(-100% - ${(GAP - 4) / zoom}px)) scale(${scale * 0.95})`,
        transformOrigin: '50% 100%',
        opacity: open ? 1 : 0,
        transition: 'opacity 0.15s ease-out, transform 0.15s cubic-bezier(0.2, 0.8, 0.2, 1)',
        pointerEvents: 'auto', // Ensure interactions work
      }}
      onPointerDown={(e) => {
        e.stopPropagation()
        // Prevent canvas panning when interacting with the popover
      }}
    >
      <div className="relative bg-white rounded-xl shadow-xl border border-slate-200/60 backdrop-blur-sm overflow-hidden">
        {children}
      </div>
      <div
        className="w-3 h-3 bg-white border-r border-b border-slate-200/60 rotate-45 -mt-1.5 z-40"
        style={{ boxShadow: '2px 2px 2px -1px rgba(0,0,0,0.05)' }}
      />
    </div>
  )
}

/* -------------------- Main Popover Component -------------------- */

export const SelectionStylePopover: React.FC = () => {
  const editor = useEditor()
  const hasSelection = useValue('has-selection', () => editor.getSelectedShapeIds().length > 0, [editor])
  const anchor = useSelectionAnchor(editor)
  const zoom = useValue('zoom', () => editor.getZoomLevel(), [editor])
  const [panel, setPanel] = useState<Panel>('none')

  useEffect(() => {
    if (!hasSelection) setPanel('none')
  }, [hasSelection])

  if (!hasSelection || !anchor) return null

  // Mini bubble
  if (panel === 'none') {
    return (
      <FadeCard anchorX={anchor.x} anchorY={anchor.y} zoom={zoom}>
        <div className="flex items-center gap-1 p-1.5">
          <IconBtn title="Fill / Color" onClick={() => setPanel('fill')}>
            <PaletteIcon />
          </IconBtn>
          <div className="w-px h-4 bg-slate-200 mx-0.5" />
          <IconBtn title="Stroke / Border" onClick={() => setPanel('stroke')}>
            <StrokeIcon />
          </IconBtn>
          <div className="w-px h-4 bg-slate-200 mx-0.5" />
          <IconBtn title="Change Shape" onClick={() => setPanel('shape')}>
            <ShapeIcon />
          </IconBtn>
        </div>
      </FadeCard>
    )
  }

  // Expanded panel
  const HeaderTabs = (
    <div className="flex items-center gap-1 mb-3 pb-3 border-b border-slate-100">
      <button
        onClick={() => setPanel('none')}
        className="w-6 h-6 flex items-center justify-center rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 mr-1 transition-colors"
        title="Back"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>
      <IconBtn title="Fill / Color" onClick={() => setPanel('fill')} active={panel === 'fill'}>
        <PaletteIcon />
      </IconBtn>
      <IconBtn title="Stroke / Border" onClick={() => setPanel('stroke')} active={panel === 'stroke'}>
        <StrokeIcon />
      </IconBtn>
      <IconBtn title="Change Shape" onClick={() => setPanel('shape')} active={panel === 'shape'}>
        <ShapeIcon />
      </IconBtn>
    </div>
  )

  const ColorGrid = (
    <div className="grid grid-cols-5 gap-2">
      {COLORS.map((c) => (
        <button
          key={c}
          onClick={() => patchSelectionStyles(editor, { color: c })}
          title={c}
          className="w-6 h-6 rounded-full border border-slate-200 hover:scale-110 transition-transform focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-blue-400"
          style={{ background: `var(--color-${c}, ${c})` }}
        />
      ))}
    </div>
  )

  const SectionLabel = ({ children }: { children: React.ReactNode }) => (
    <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">{children}</div>
  )

  const ChipBtn = ({ children, onClick, active }: { children: React.ReactNode, onClick: () => void, active?: boolean }) => (
    <button
      onClick={onClick}
      className={`
        px-3 py-1.5 text-xs font-medium rounded-md border transition-all
        ${active
          ? 'bg-blue-50 border-blue-200 text-blue-700'
          : 'bg-white border-slate-200 text-slate-600 hover:border-slate-300 hover:bg-slate-50'
        }
      `}
    >
      {children}
    </button>
  )

  return (
    <FadeCard anchorX={anchor.x} anchorY={anchor.y} zoom={zoom}>
      <div className="p-3 w-64">
        {HeaderTabs}

        {panel === 'fill' && (
          <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
            <div>
              <SectionLabel>Fill Type</SectionLabel>
              <div className="flex gap-2">
                <ChipBtn onClick={() => patchSelectionStyles(editor, { fill: 'none' })}>None</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { fill: 'semi' })}>Semi</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { fill: 'solid' })}>Solid</ChipBtn>
              </div>
            </div>
            <div>
              <SectionLabel>Color</SectionLabel>
              {ColorGrid}
            </div>
          </div>
        )}

        {panel === 'stroke' && (
          <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
            <div>
              <SectionLabel>Size</SectionLabel>
              <div className="flex gap-2">
                {STROKE_SIZES.map((s) => (
                  <ChipBtn key={s} onClick={() => patchSelectionStyles(editor, { size: s })}>
                    {s.toUpperCase()}
                  </ChipBtn>
                ))}
              </div>
            </div>
            <div>
              <SectionLabel>Style</SectionLabel>
              <div className="flex gap-2">
                <ChipBtn onClick={() => patchSelectionStyles(editor, { dash: 'draw' })}>Draw</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { dash: 'solid' })}>Solid</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { dash: 'dashed' })}>Dash</ChipBtn>
              </div>
            </div>
            <div>
              <SectionLabel>Rounding</SectionLabel>
              <div className="flex gap-2">
                <ChipBtn onClick={() => patchSelectionStyles(editor, { rounding: 0 })}>Sharp</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { rounding: 8 })}>Round</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { rounding: 24 })}>Pill</ChipBtn>
              </div>
            </div>
            <div>
              <SectionLabel>Color</SectionLabel>
              {ColorGrid}
            </div>
          </div>
        )}

        {panel === 'shape' && (
          <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-200">
            <div>
              <SectionLabel>Shape Type</SectionLabel>
              <div className="grid grid-cols-2 gap-2">
                <ChipBtn onClick={() => patchSelectionStyles(editor, { geo: 'rectangle' })}>Rectangle</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { geo: 'ellipse' })}>Ellipse</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { geo: 'triangle' })}>Triangle</ChipBtn>
                <ChipBtn onClick={() => patchSelectionStyles(editor, { geo: 'diamond' })}>Diamond</ChipBtn>
              </div>
            </div>
            <div className="text-[10px] text-slate-400 italic">
              Applies to geometric shapes only.
            </div>
          </div>
        )}
      </div>
    </FadeCard>
  )
}
