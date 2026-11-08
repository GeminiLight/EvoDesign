import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import './index.css'
import './styles/studio.css'
import { BackendAuthProvider } from './features/auth/BackendAuthProvider'
import { LanguageProvider } from './i18n/LanguageProvider'
import { ToastProvider } from './components/Toast'
import { SkipLink } from './components/SkipLink'
import { RouteErrorScreen } from './components/RouteErrorScreen'
import { GuestImportPrompt } from './components/GuestImportPrompt'
import { AppRoutes } from './AppRoutes'

// A data router (rather than <BrowserRouter>) is required for useBlocker, which
// the workspace uses to stop in-app and browser Back navigation from dropping
// unsaved edits. The existing <Routes> tree is mounted under one splat route.
const router = createBrowserRouter([{ path: '*', element: <AppRoutes />, errorElement: <RouteErrorScreen /> }])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Language and Toast wrap the auth provider so it can report OAuth
        callback failures to the user; every existing consumer stays inside
        all three. */}
    <LanguageProvider>
      <ToastProvider>
        <BackendAuthProvider>
        <SkipLink />
        <RouterProvider router={router} />
        <GuestImportPrompt />
        </BackendAuthProvider>
      </ToastProvider>
    </LanguageProvider>
  </StrictMode>,
)
