'use client'

import TldrawRenderer from '../../components/TldrawRenderer'
import { TLEditorSnapshot } from 'tldraw'
import { Suspense, useEffect, useState } from 'react'

declare global {
  interface Window {
    loadTldrawSnapshot: (snapshot: TLEditorSnapshot) => void;
    __renderStatus: string;
    __renderError: string;
  }
}

function Renderer() {
  const [snapshot, setSnapshot] = useState<TLEditorSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    window.__renderStatus = 'idle';
    window.__renderError = '';

    window.loadTldrawSnapshot = (incomingSnapshot) => {
      if (!incomingSnapshot || !incomingSnapshot.document) {
        const message = 'Injected TLDraw snapshot is missing document.';
        window.__renderStatus = 'error';
        window.__renderError = message;
        setError(message);
        setSnapshot(null);
        return;
      }
      window.__renderStatus = 'loading';
      window.__renderError = '';
      setError(null);
      setSnapshot(incomingSnapshot);
    };

    return () => {
      delete (window as any).loadTldrawSnapshot;
    };
  }, []);

  if (error) {
    return (
      <div id="render-error" style={{ padding: '20px', color: 'red', fontFamily: 'monospace' }}>
        <h1>Data Injection Error</h1>
        <pre>{error}</pre>
      </div>
    );
  }

  if (snapshot) {
    return (
      <TldrawRenderer
        snapshot={snapshot}
        onReady={() => {
          window.__renderStatus = 'ready';
        }}
      />
    );
  }

  return <div>Waiting for data injection...</div>;
}

export default function Home() {
  return (
    <main>
      <Suspense fallback={<div>Loading...</div>}>
        <Renderer />
      </Suspense>
    </main>
  );
}
