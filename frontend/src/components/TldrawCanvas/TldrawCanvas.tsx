import { useCallback, useEffect, useRef } from 'react';
import { Tldraw, type Editor, loadSnapshot, getSnapshot, type TLEditorSnapshot, type TLStoreSnapshot } from '@tldraw/tldraw';
import { CanvasLoadingScreen } from '../DiagramCanvas/CanvasLoadingScreen';
import { isTldrawPayload } from '../../utils/app';

import '@tldraw/tldraw/tldraw.css';

export type TldrawCanvasProps = {
  elements?: Array<unknown>;
  snapshot?: TLEditorSnapshot | TLStoreSnapshot | Record<string, unknown> | null;
  onSnapshotChange?: (snapshot: TLEditorSnapshot) => void;
  onSelectionChange?: (selectedIds: string[]) => void;
  onRenderError?: (error: Error) => void;
};

const isObjectRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

export function TldrawCanvas({ snapshot, onSnapshotChange, onSelectionChange, onRenderError }: TldrawCanvasProps) {
  const editorRef = useRef<Editor | null>(null);
  const unlistenRef = useRef<(() => void) | null>(null);
  const selectionUnlistenRef = useRef<(() => void) | null>(null);
  const snapshotFrameRef = useRef<number | null>(null);
  const flushSnapshotFrameRef = useRef<(() => void) | null>(null);
  const isApplyingExternalSnapshotRef = useRef(false);
  const onSnapshotChangeRef = useRef<typeof onSnapshotChange>(onSnapshotChange);
  const onSelectionChangeRef = useRef<typeof onSelectionChange>(onSelectionChange);
  const onRenderErrorRef = useRef<typeof onRenderError>(onRenderError);

  useEffect(() => {
    onSnapshotChangeRef.current = onSnapshotChange;
  }, [onSnapshotChange]);

  useEffect(() => {
    onSelectionChangeRef.current = onSelectionChange;
  }, [onSelectionChange]);

  useEffect(() => {
    onRenderErrorRef.current = onRenderError;
  }, [onRenderError]);

  const isRootStoreSnapshot = useCallback((value: unknown): value is TLStoreSnapshot => {
    if (!isObjectRecord(value)) {
      return false;
    }

    return (
      isObjectRecord(value.store)
      && isObjectRecord(value.schema)
    );
  }, []);

  const sanitizeLegacySnapshot = useCallback((incomingSnapshot: unknown): unknown => {
    if (!isObjectRecord(incomingSnapshot)) {
      return incomingSnapshot;
    }

    let cloned: Record<string, unknown>;
    try {
      cloned = JSON.parse(JSON.stringify(incomingSnapshot)) as Record<string, unknown>;
    } catch {
      return incomingSnapshot;
    }

    const sanitizeRecords = (records: unknown) => {
      if (!isObjectRecord(records)) {
        return;
      }

      for (const record of Object.values(records)) {
        if (!isObjectRecord(record)) {
          continue;
        }

        const props = record.props;
        if (
          record.typeName === 'shape' &&
          record.type === 'geo' &&
          isObjectRecord(props) &&
          'text' in props
        ) {
          delete props.text;
        }
      }
    };

    sanitizeRecords(cloned.records);
    sanitizeRecords(cloned.store);
    const document = cloned.document;
    sanitizeRecords(isObjectRecord(document) ? document.store ?? document : document);

    return cloned;
  }, []);

  const applySnapshot = useCallback((editor: Editor, incomingSnapshot: TLEditorSnapshot | TLStoreSnapshot | Record<string, unknown> | null | undefined) => {
    if (!incomingSnapshot || !isTldrawPayload(incomingSnapshot)) return;

    try {
      isApplyingExternalSnapshotRef.current = true;
      const sanitizedSnapshot = sanitizeLegacySnapshot(incomingSnapshot);

      if (!isObjectRecord(sanitizedSnapshot)) {
        return;
      }

      if (sanitizedSnapshot.document && sanitizedSnapshot.session) {
        loadSnapshot(editor.store, sanitizedSnapshot as Partial<TLEditorSnapshot>);
      } else if (isRootStoreSnapshot(sanitizedSnapshot)) {
        loadSnapshot(editor.store, sanitizedSnapshot);
      } else if (sanitizedSnapshot.records) {
        const current = getSnapshot(editor.store);
        const mergedSnapshot = sanitizeLegacySnapshot({
          ...current,
          document: sanitizedSnapshot.records,
          session: current.session,
        });
        loadSnapshot(editor.store, mergedSnapshot as Partial<TLEditorSnapshot>);
      }
    } catch (error) {
      const normalizedError = error instanceof Error ? error : new Error('TLDraw snapshot load failed');
      console.error('Failed to load snapshot:', normalizedError);
      onRenderErrorRef.current?.(normalizedError);
    } finally {
      setTimeout(() => {
        isApplyingExternalSnapshotRef.current = false;
      }, 0);
    }
  }, [isRootStoreSnapshot, sanitizeLegacySnapshot]);

  const handleMount = useCallback((editor: Editor) => {
    editorRef.current = editor;
    applySnapshot(editor, snapshot);

    unlistenRef.current?.();
    selectionUnlistenRef.current?.();
    flushSnapshotFrameRef.current?.();

    // getSnapshot() clones the whole store, so coalesce the many store events a
    // single interaction emits into at most one clone per animation frame.
    const emitSnapshot = () => {
      snapshotFrameRef.current = null;
      if (isApplyingExternalSnapshotRef.current) {
        return;
      }

      onSnapshotChangeRef.current?.(getSnapshot(editor.store));
    };

    flushSnapshotFrameRef.current = () => {
      if (snapshotFrameRef.current === null) {
        return;
      }

      cancelAnimationFrame(snapshotFrameRef.current);
      emitSnapshot();
    };

    unlistenRef.current = editor.store.listen(() => {
      if (isApplyingExternalSnapshotRef.current) {
        return;
      }

      if (snapshotFrameRef.current !== null) {
        return;
      }

      snapshotFrameRef.current = requestAnimationFrame(emitSnapshot);
    }, { source: 'user', scope: 'document' });

    // Listen to selection changes separately to avoid re-render loops
    let prevSelectedIds: string[] = [];
    const selectionUnsub = editor.store.listen(() => {
      const ids = editor.getSelectedShapeIds();
      const sorted = [...ids].sort();
      if (sorted.length !== prevSelectedIds.length || sorted.some((id, i) => id !== prevSelectedIds[i])) {
        prevSelectedIds = sorted;
        onSelectionChangeRef.current?.(sorted);
      }
    }, { source: 'user', scope: 'session' });
    selectionUnlistenRef.current = selectionUnsub;
  }, [applySnapshot, snapshot]);

  useEffect(() => {
    const editor = editorRef.current;
    if (editor) {
      applySnapshot(editor, snapshot);
    }
  }, [applySnapshot, snapshot]);

  useEffect(() => {
    return () => {
      if (unlistenRef.current) {
        unlistenRef.current();
        unlistenRef.current = null;
      }
      if (selectionUnlistenRef.current) {
        selectionUnlistenRef.current();
        selectionUnlistenRef.current = null;
      }
      // Listeners are unbound first so this cannot arm another frame; the
      // pending change is flushed synchronously instead of being dropped.
      if (flushSnapshotFrameRef.current) {
        flushSnapshotFrameRef.current();
        flushSnapshotFrameRef.current = null;
      }
    };
  }, []);

  return (
    <div className="relative h-full w-full overflow-hidden rounded-3xl border border-sky-100 bg-white shadow-[0_25px_60px_rgba(15,23,42,0.08)]">
      <Tldraw
        autoFocus
        inferDarkMode={false}
        onMount={handleMount}
        components={{
          // OnTheCanvas: () => <SelectionStylePopover />,
          // MenuPanel: null,
          DebugMenu: null,
          LoadingScreen: () => <CanvasLoadingScreen />,
          // StylePanel: null,
          // Toolbar: null,
        }}
      />
    </div>
  );
}

export default TldrawCanvas;
