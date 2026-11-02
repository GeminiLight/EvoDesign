import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { BROWSER_MODE } from './services/browser/runtime';
import { BrowserModelSettings } from './components/BrowserModelSettings';
import { RouteScrollReset } from './components/RouteScrollReset';
import { AppLoadingScreen } from './components/AppLoadingScreen';

// Route pages load on demand so heavy editor code (tldraw, Excalidraw) is only
// downloaded by the routes that render it.
const IndexPage = lazy(() => import('./pages/IndexPage').then(m => ({ default: m.IndexPage })));
const WorkspacePage = lazy(() => import('./pages/WorkspacePage'));
const HomePage = lazy(() => import('./pages/HomePage').then(m => ({ default: m.HomePage })));
const EmailAuthPage = lazy(() => import('./pages/EmailAuthPage').then(m => ({ default: m.EmailAuthPage })));
const DashboardPage = lazy(() => import('./pages/DashboardPage').then(m => ({ default: m.DashboardPage })));
const GalleryPage = lazy(() => import('./pages/GalleryPage').then(m => ({ default: m.GalleryPage })));
const YourDNAPage = lazy(() => import('./pages/YourDNAPage').then(m => ({ default: m.YourDNAPage })));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage').then(m => ({ default: m.NotFoundPage })));
const AgentConnectPage = lazy(() => import('./pages/AgentConnectPage').then(m => ({ default: m.AgentConnectPage })));

export function AppRoutes() {
  return (
    <>
      <RouteScrollReset />
      {BROWSER_MODE && <BrowserModelSettings />}
      <Suspense fallback={<AppLoadingScreen />}>
        <Routes>
          <Route path="/agent/connect" element={<AgentConnectPage />} />
          <Route path="/" element={BROWSER_MODE ? <Navigate to="/home" replace /> : <IndexPage />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/projects" element={<DashboardPage />} />
          <Route path="/dashboard" element={<Navigate to="/projects" replace />} />
          <Route path="/insights" element={<GalleryPage />} />
          <Route path="/insight" element={<Navigate to="/insights" replace />} />
          <Route path="/gallery" element={<Navigate to="/insights" replace />} />
          <Route path="/dna" element={<YourDNAPage />} />
          <Route path="/auth" element={<Navigate to="/auth/email" replace />} />
          <Route path="/login" element={BROWSER_MODE ? <Navigate to="/home" replace /> : <EmailAuthPage />} />
          <Route path="/signin" element={BROWSER_MODE ? <Navigate to="/home" replace /> : <EmailAuthPage />} />
          <Route path="/sign-in" element={BROWSER_MODE ? <Navigate to="/home" replace /> : <EmailAuthPage />} />
          <Route path="/auth/email" element={BROWSER_MODE ? <Navigate to="/home" replace /> : <EmailAuthPage />} />
          <Route path="/workspace" element={<WorkspacePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Suspense>
    </>
  );
}
