/**
 * API client — base URL, token storage, and typed endpoint helpers.
 */

export const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';
export const WS_BASE = API_BASE.replace(/^http/, 'ws');

const TOKEN_KEY = 'sa_token';

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

/* ─── Types ─── */

export interface UserOut {
  id: number;
  email: string;
  role: 'admin' | 'analyst';
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserOut;
}

export interface ReportSummary {
  id: number;
  symbol: string;
  query: string;
  created_at: string;
}

export interface ReportDetail extends ReportSummary {
  report_md: string;
  data_json: string;
}

/* ─── Admin types ─── */

export interface AuditLogEntry {
  id: number;
  actor_email: string;
  action: string;
  target: string;
  detail: string;
  ip: string;
  created_at: string;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  total: number;
}

export interface AdminStats {
  total_users: number;
  admin_count: number;
  analyst_count: number;
  total_reports: number;
  reports_last_7d: number;
  recent_events: AuditLogEntry[];
}

export interface SystemSettings {
  registration_open: boolean;
  default_role: 'admin' | 'analyst';
  session_timeout_minutes: number;
}

export type SystemSettingsUpdate = Partial<SystemSettings>;

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

/* ─── Fetch helpers ─── */

async function parseError(res: Response): Promise<never> {
  let detail = `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body.detail === 'string') detail = body.detail;
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
  } catch {
    /* non-JSON error body */
  }
  throw new ApiError(res.status, detail);
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Content-Type', 'application/json');
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) await parseError(res);
  // 204 No Content (e.g. DELETE) has an empty body — don't try to parse it.
  if (res.status === 204 || res.headers.get('content-length') === '0') {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

/* ─── Endpoints ─── */

export const api = {
  register: (email: string, password: string) =>
    apiFetch<TokenResponse>('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    apiFetch<TokenResponse>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  me: () => apiFetch<UserOut>('/api/auth/me'),

  listUsers: () => apiFetch<{ users: UserOut[] }>('/api/auth/users'),

  updateRole: (userId: number, role: 'admin' | 'analyst') =>
    apiFetch<UserOut>(`/api/auth/users/${userId}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    }),

  history: () => apiFetch<ReportSummary[]>('/api/research/history'),

  reportDetail: (id: number) => apiFetch<ReportDetail>(`/api/research/history/${id}`),

  /* ─── Admin console ─── */

  adminStats: () => apiFetch<AdminStats>('/api/admin/stats'),

  createUser: (email: string, password: string, role: 'admin' | 'analyst' = 'analyst') =>
    apiFetch<UserOut>('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({ email, password, role }),
    }),

  deleteUser: (userId: number) =>
    apiFetch<void>(`/api/admin/users/${userId}`, { method: 'DELETE' }),

  resetPassword: (userId: number, newPassword: string) =>
    apiFetch<UserOut>(`/api/admin/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword }),
    }),

  auditLog: (params: { limit?: number; offset?: number; action?: string } = {}) => {
    const qs = new URLSearchParams();
    if (params.limit != null) qs.set('limit', String(params.limit));
    if (params.offset != null) qs.set('offset', String(params.offset));
    if (params.action) qs.set('action', params.action);
    const query = qs.toString();
    return apiFetch<AuditLogResponse>(`/api/admin/audit${query ? `?${query}` : ''}`);
  },

  getSettings: () => apiFetch<SystemSettings>('/api/admin/settings'),

  updateSettings: (updates: SystemSettingsUpdate) =>
    apiFetch<SystemSettings>('/api/admin/settings', {
      method: 'PATCH',
      body: JSON.stringify(updates),
    }),
};
