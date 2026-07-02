import './index.css'
import ErrorBoundary from './components/ErrorBoundary'
import { AuthProvider, useAuth } from './context/AuthContext'
import LoginPage from './pages/LoginPage'
import StockAnalystDashboard from './pages/StockAnalystDashboard'

function Gate() {
  const { user, initializing } = useAuth()

  if (initializing) {
    return (
      <div className="min-h-screen bg-ink-950 flex items-center justify-center" role="status" aria-label="Loading">
        <div className="w-8 h-8 rounded-full border-2 border-ink-700 border-t-emerald-400 animate-spin" />
      </div>
    )
  }

  return user ? <StockAnalystDashboard /> : <LoginPage />
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
