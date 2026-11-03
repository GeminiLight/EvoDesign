'use client'

import { Tldraw, TLEditorSnapshot } from 'tldraw'
import 'tldraw/tldraw.css'
import ErrorBoundary from './ErrorBoundary'

interface TldrawRendererProps {
  snapshot: TLEditorSnapshot | null
  onReady?: () => void
}

export default function TldrawRenderer({ snapshot, onReady }: TldrawRendererProps) {
  if (!snapshot) {
    return (
      <div id="render-error" style={{ padding: '20px', color: 'red' }}>
        <h1>Data Loading Error</h1>
        <p>No valid tldraw snapshot data was provided.</p>
      </div>
    )
  }

  return (
    <ErrorBoundary>
      <div className="tldraw__editor" style={{ position: 'fixed', inset: 0 }}>
        <Tldraw
          snapshot={snapshot}
          hideUi
          onMount={(editor) => {
            editor.zoomToFit()
            window.setTimeout(() => onReady?.(), 500)
          }}
        />
      </div>
    </ErrorBoundary>
  )
}
