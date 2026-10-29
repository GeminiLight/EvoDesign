import { BROWSER_MODE } from './services/browser/runtime'
import { BrowserModelSettings } from './components/BrowserModelSettings'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import './styles/studio.css'
import { IndexPage } from './pages/IndexPage'
import { BackendAuthProvider } from './features/auth/BackendAuthProvider'
import { WorkspacePage } from './pages/WorkspacePage'
import { HomePage } from './pages/HomePage'
import { LanguageProvider } from './i18n/LanguageProvider'
import { ToastProvider } from './components/Toast'
import { SkipLink } from './components/SkipLink'
import { RouteScrollReset } from './components/RouteScrollReset'
import { GuestImportPrompt } from './components/GuestImportPrompt'
import { EmailAuthPage } from './pages/EmailAuthPage'
import { DashboardPage } from './pages/DashboardPage'
import { GalleryPage } from './pages/GalleryPage'
import { YourDNAPage } from './pages/YourDNAPage'
import { NotFoundPage } from './pages/NotFoundPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Language and Toast wrap the auth provider so it can report OAuth
        callback failures to the user; every existing consumer stays inside
        all three. */}
    <LanguageProvider>
      <ToastProvider>
        <BackendAuthProvider>
        <SkipLink />
        <BrowserRouter>
          <RouteScrollReset />
          {BROWSER_MODE && <BrowserModelSettings />}
          <Routes>
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
        </BrowserRouter>
        <GuestImportPrompt />
        </BackendAuthProvider>
      </ToastProvider>
    </LanguageProvider>
  </StrictMode>,
)
