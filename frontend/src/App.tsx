import { useState, lazy, Suspense } from 'react'
import './index.css'
import ErrorBoundary from './components/ErrorBoundary'
import { AuthProvider, useAuth } from './context/AuthContext'
import LoginPage from './pages/LoginPage'
import { GoogleOAuthProvider } from '@react-oauth/google'

// Lazy-load heavy pages — reduces initial bundle size significantly.
// AdminConsole (~25KB) and StockAnalystDashboard (~20KB) + react-markdown
// are only loaded when the user navigates to them.
const StockAnalystDashboard = lazy(() => import('./pages/StockAnalystDashboard'))
const AdminConsole = lazy(() => import('./pages/AdminConsole'))

function LoadingSpinner() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center" role="status" aria-label="Loading page">
      <div className="flex flex-col items-center gap-3">
        <div className="w-10 h-10 rounded-full border-2 border-muted border-t-primary animate-spin" />
        <span className="text-muted-foreground text-sm">Loading...</span>
      </div>
    </div>
  )
}

function Gate() {
  const { user, initializing } = useAuth()
  // Admins land on the console; this toggles them to the research view and back.
  // Analysts never see the console, so the flag is simply ignored for them.
  const [showResearch, setShowResearch] = useState(false)

  if (initializing) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center" role="status" aria-label="Loading">
        <div className="w-8 h-8 rounded-full border-2 border-muted border-t-primary animate-spin" />
      </div>
    )
  }

  if (!user) return <LoginPage />

  const isAdmin = user.role === 'admin'

  if (isAdmin && !showResearch) {
    return (
      <Suspense fallback={<LoadingSpinner />}>
        <AdminConsole onExit={() => setShowResearch(true)} />
      </Suspense>
    )
  }

  return (
    <Suspense fallback={<LoadingSpinner />}>
      <StockAnalystDashboard
        onOpenAdmin={isAdmin ? () => setShowResearch(false) : undefined}
      />
    </Suspense>
  )
}

export default function App() {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID || ''

  return (
    <ErrorBoundary>
      <GoogleOAuthProvider clientId={clientId}>
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </GoogleOAuthProvider>
    </ErrorBoundary>
  )
}
