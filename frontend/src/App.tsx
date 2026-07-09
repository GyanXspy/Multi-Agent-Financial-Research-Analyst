import { useState } from 'react'
import './index.css'
import ErrorBoundary from './components/ErrorBoundary'
import { AuthProvider, useAuth } from './context/AuthContext'
import LoginPage from './pages/LoginPage'
import StockAnalystDashboard from './pages/StockAnalystDashboard'
import AdminConsole from './pages/AdminConsole'

function Gate() {
  const { user, initializing } = useAuth()
  // Admins land on the console; this toggles them to the research view and back.
  // Analysts never see the console, so the flag is simply ignored for them.
  const [showResearch, setShowResearch] = useState(false)

  if (initializing) {
    return (
      <div className="min-h-screen bg-ink-950 flex items-center justify-center" role="status" aria-label="Loading">
        <div className="w-8 h-8 rounded-full border-2 border-ink-700 border-t-emerald-400 animate-spin" />
      </div>
    )
  }

  if (!user) return <LoginPage />

  const isAdmin = user.role === 'admin'

  if (isAdmin && !showResearch) {
    return <AdminConsole onExit={() => setShowResearch(true)} />
  }

  return (
    <StockAnalystDashboard
      onOpenAdmin={isAdmin ? () => setShowResearch(false) : undefined}
    />
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Gate />
      </AuthProvider>
    </ErrorBoundary>
  )
}
