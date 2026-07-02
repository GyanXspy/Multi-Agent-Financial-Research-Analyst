/**
 * Login / Register page — single card with mode toggle.
 */

import { useState } from 'react';
import type { FormEvent } from 'react';
import { useAuth } from '../context/AuthContext';

export default function LoginPage() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');

    if (mode === 'register' && password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }

    setSubmitting(true);
    try {
      if (mode === 'login') await login(email, password);
      else await register(email, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-ink-950 flex items-center justify-center px-4 relative overflow-hidden">
      {/* Ambient background glow */}
      <div aria-hidden="true" className="absolute inset-0 pointer-events-none">
        <div className="absolute -top-40 left-1/2 -translate-x-1/2 w-[600px] h-[400px] rounded-full bg-emerald-500/10 blur-[120px]" />
        <div className="absolute bottom-0 right-0 w-[400px] h-[300px] rounded-full bg-teal-500/5 blur-[100px]" />
      </div>

      <div className="w-full max-w-md relative">
        {/* Brand */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2.5 mb-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <svg className="w-5 h-5 text-ink-950" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 17l6-6 4 4 8-8M15 7h6v6" />
              </svg>
            </div>
          </div>
          <h1 className="font-display text-2xl font-bold text-white tracking-tight">
            Multi-Agent Financial Analyst
          </h1>
          <p className="text-ink-400 text-sm mt-1.5">
            AI-powered equity research, in real time
          </p>
        </div>

        {/* Card */}
        <div className="bg-ink-900/80 backdrop-blur border border-ink-800 rounded-2xl p-7 shadow-2xl">
          {/* Mode toggle */}
          <div className="grid grid-cols-2 gap-1 bg-ink-950/80 rounded-xl p-1 mb-6" role="tablist" aria-label="Authentication mode">
            {(['login', 'register'] as const).map((m) => (
              <button
                key={m}
                role="tab"
                aria-selected={mode === m}
                onClick={() => { setMode(m); setError(''); }}
                className={`py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400 ${
                  mode === m
                    ? 'bg-ink-800 text-white shadow-sm'
                    : 'text-ink-400 hover:text-ink-200'
                }`}
              >
                {m === 'login' ? 'Sign In' : 'Create Account'}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            <div>
              <label htmlFor="email" className="block text-xs font-semibold text-ink-300 uppercase tracking-wider mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="w-full bg-ink-950 border border-ink-700 rounded-xl px-4 py-3 text-sm text-white placeholder-ink-500 focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400/40 transition-colors"
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-xs font-semibold text-ink-300 uppercase tracking-wider mb-1.5">
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                required
                minLength={mode === 'register' ? 8 : 1}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === 'register' ? 'At least 8 characters' : '••••••••'}
                className="w-full bg-ink-950 border border-ink-700 rounded-xl px-4 py-3 text-sm text-white placeholder-ink-500 focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400/40 transition-colors"
              />
            </div>

            {error && (
              <div role="alert" className="bg-rose-500/10 border border-rose-500/30 text-rose-300 text-sm rounded-xl px-4 py-3">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={submitting}
              className="w-full bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 disabled:from-ink-700 disabled:to-ink-700 disabled:text-ink-400 text-ink-950 font-bold py-3 rounded-xl transition-all shadow-lg shadow-emerald-500/20 disabled:shadow-none cursor-pointer disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
            >
              {submitting ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
            </button>
          </form>

          {mode === 'register' && (
            <p className="text-ink-500 text-xs text-center mt-4">
              The first account created becomes the administrator.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
