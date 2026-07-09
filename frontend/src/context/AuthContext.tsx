/**
 * Auth context — holds the current user, exposes login/register/logout,
 * and restores the session from a stored token on mount.
 */

import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api, clearToken, getToken, setToken } from '../lib/api';
import type { UserOut } from '../lib/api';

interface AuthContextValue {
  user: UserOut | null;
  initializing: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [initializing, setInitializing] = useState(true);

  // Restore session on mount
  useEffect(() => {
    if (!getToken()) {
      setInitializing(false);
      return;
    }
    api
      .me()
      .then(setUser)
      .catch((err) => {
        // Only clear the token on genuine auth failures (401/403).
        // Network errors or 5xx should not silently log the user out —
        // the token may still be valid once the server recovers.
        const isAuthError =
          err && typeof err === 'object' && 'status' in err &&
          (err.status === 401 || err.status === 403);
        if (isAuthError) {
          clearToken();
        } else {
          console.warn('Session restore failed (non-auth error):', err);
        }
      })
      .finally(() => setInitializing(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await api.login(email, password);
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    const res = await api.register(email, password);
    setToken(res.access_token);
    setUser(res.user);
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, initializing, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
