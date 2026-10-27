'use client';

import React, { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import {
    DEFAULT_EXCALIDRAW_EXPORT_SCALE,
    DEFAULT_RENDER_MARGIN,
} from '@/lib/renderDefaults';

const Excalidraw = dynamic(
    () => import('@excalidraw/excalidraw').then((mod) => mod.Excalidraw),
    { ssr: false }
);

declare global {
    interface Window {
        loadExcalidrawScene: (scene: any) => void;
        __renderStatus: string;
        __renderError: string;
        __pendingScene: any;
        __exportedImageData: string | null;
        __exportScale: number;
        __exportMargin: number;
        __excalidrawAPI: any;
    }
}

const defaultAppState = {
    viewModeEnabled: true,
    zenModeEnabled: true,
    gridSize: undefined,
    viewBackgroundColor: '#ffffff'
};

export default function ExcalidrawRendererPage() {
    const [excalidrawAPI, setExcalidrawAPI] = useState<any>(null);

    useEffect(() => {
        window.__renderStatus = 'idle';
        window.__renderError = '';
        window.__pendingScene = null;
        window.__exportedImageData = null;
        window.__exportMargin = 40;

        window.loadExcalidrawScene = async (scene) => {
            try {
                window.__renderStatus = 'loading';
                window.__renderError = '';
                window.__exportedImageData = null;
                if (!window.__excalidrawAPI) {
                    window.__pendingScene = scene;
                    return;
                }
                const api = window.__excalidrawAPI;
                const normalized = Array.isArray(scene) ? { elements: scene } : scene;
                const appState = Object.assign({}, defaultAppState, normalized.appState || {});
                const payload = Object.assign({}, normalized, { appState });

                api.updateScene(payload);
                if (payload.files && api.addFiles) {
                    api.addFiles(Object.values(payload.files));
                }
                if (api.scrollToContent && payload.elements) {
                    api.scrollToContent(payload.elements, { fitToContent: true });
                }

                await document.fonts.ready;
                await new Promise((resolve) => requestAnimationFrame(resolve));

                const { exportToBlob, restoreElements } = await import('@excalidraw/excalidraw');
                // The editor's initial hydration can replace its scene after
                // updateScene. Export the submitted scene directly so the
                // first snapshot cannot silently become an empty canvas.
                const exportElements = restoreElements(normalized.elements || [], null);
                const exportScale = Number(window.__exportScale ?? DEFAULT_EXCALIDRAW_EXPORT_SCALE);
                const exportMargin = Number(window.__exportMargin ?? DEFAULT_RENDER_MARGIN);
                const blob = await exportToBlob({
                    elements: exportElements,
                    appState: {
                        ...appState,
                        exportWithDarkMode: false,
                        exportBackground: true,
                        exportScale,
                    },
                    files: normalized.files || {},
                    mimeType: 'image/png',
                    exportPadding: exportMargin,
                    getDimensions: (width: number, height: number) => ({
                        width: width * exportScale,
                        height: height * exportScale,
                        scale: exportScale,
                    }),
                });

                window.__exportedImageData = await new Promise<string>((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onload = () => {
                        if (typeof reader.result === 'string') {
                            resolve(reader.result);
                        } else {
                            reject(new Error('Excalidraw export did not produce a data URL.'));
                        }
                    };
                    reader.onerror = () => reject(new Error('Failed to read exported Excalidraw blob.'));
                    reader.readAsDataURL(blob);
                });
                window.__renderStatus = 'ready';
            } catch (err: any) {
                console.error("Excalidraw render error:", err);
                window.__renderStatus = 'error';
                window.__renderError = err?.message || String(err);
            }
        };

        if (window.__pendingScene && excalidrawAPI) {
            window.loadExcalidrawScene(window.__pendingScene);
            window.__pendingScene = null;
        }
    }, [excalidrawAPI]);

    return (
        <div style={{ width: '100vw', height: '100vh', overflow: 'hidden' }}>
            <Excalidraw
                excalidrawAPI={(api) => {
                    setExcalidrawAPI(api);
                    window.__excalidrawAPI = api;
                    if (window.__pendingScene) {
                        window.loadExcalidrawScene(window.__pendingScene);
                        window.__pendingScene = null;
                    }
                }}
                initialData={{ elements: [], appState: defaultAppState }}
                viewModeEnabled={true}
                zenModeEnabled={true}
            />
        </div>
    );
}
