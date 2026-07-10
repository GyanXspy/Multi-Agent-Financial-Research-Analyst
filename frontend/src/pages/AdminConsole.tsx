/**
 * AdminConsole — the dedicated admin dashboard, distinct from the research view.
 *
 * Tabs:
 *  - Overview  : activity stats + recent events (oversight at a glance)
 *  - Users     : create / reset-password / delete accounts (user management)
 *  - Reports   : read-only browse of every user's saved research (data access)
 *  - Audit Log : full, filterable trail of security-relevant events (oversight)
 *  - Settings  : runtime-enforced system configuration
 *
 * Every panel calls admin-gated endpoints; the backend is the source of truth
 * for what the single configured admin may do (e.g. it forbids deleting the
 * designated admin), so the UI surfaces those errors rather than duplicating
 * the rules.
 */

import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';

import { api } from '../lib/api';
import type {
  AdminStats,
  AuditLogEntry,
  ReportSummary,
  SystemSettings,
  UserOut,
} from '../lib/api';
import { useAuth } from '../context/AuthContext';
import MetricCard from '../components/MetricCard';

/* ─── Shared helpers ─── */

const TABS = ['Overview', 'Users', 'Reports', 'Audit Log', 'Settings'] as const;
type Tab = (typeof TABS)[number];

function fmtDate(iso: string): string {
  // Stored timestamps are naive UTC; append Z so the browser localizes them.
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function Panel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="bg-card border border-border  shadow-lg">
      <div className="flex items-center justify-between gap-3 px-5 py-4 border-b border-border">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">{title}</h2>
        {action}
      </div>
      <div className="p-5">{children}</div>
    </section>
  );
}

function ErrorLine({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div role="alert" className="bg-destructive/10 border border-destructive/30 text-rose-300 text-xs  px-3.5 py-2.5 mb-3">
      {message}
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const admin = role === 'admin';
  return (
    <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5  ${admin ? 'bg-primary/15 text-emerald-300' : 'bg-muted text-muted-foreground'}`}>
      {role}
    </span>
  );
}

/* ─── Overview ─── */

function OverviewPanel() {
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    api.adminStats().then(setStats).catch((e) => setError(e instanceof Error ? e.message : 'Failed to load stats'));
  }, []);

  return (
    <div className="space-y-5">
      <ErrorLine message={error} />
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <MetricCard label="Total Users" value={stats ? String(stats.total_users) : '—'} accent />
        <MetricCard label="Admins" value={stats ? String(stats.admin_count) : '—'} />
        <MetricCard label="Analysts" value={stats ? String(stats.analyst_count) : '—'} />
        <MetricCard label="Reports" value={stats ? String(stats.total_reports) : '—'} accent />
        <MetricCard label="Reports · 7d" value={stats ? String(stats.reports_last_7d) : '—'} />
      </div>

      <Panel title="Recent Activity">
        {stats && stats.recent_events.length === 0 && (
          <p className="text-muted-foreground text-sm">No recorded events yet.</p>
        )}
        <ul className="divide-y divide-border/70">
          {stats?.recent_events.map((e) => (
            <li key={e.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
              <div className="min-w-0">
                <span className="text-muted-foreground font-medium">{e.action}</span>
                {e.target && <span className="text-muted-foreground"> · {e.target}</span>}
              </div>
              <span className="text-muted-foreground text-[11px] shrink-0">{fmtDate(e.created_at)}</span>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

/* ─── Users ─── */

function UsersPanel() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Create form
  const [newEmail, setNewEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [creating, setCreating] = useState(false);

  const load = useCallback(() => {
    api.listUsers().then((r) => setUsers(r.users)).catch((e) => setError(e instanceof Error ? e.message : 'Failed to load users'));
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setNotice('');
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setCreating(true);
    try {
      await api.createUser(newEmail.trim(), newPassword, 'analyst');
      setNotice(`Created ${newEmail.trim()}.`);
      setNewEmail('');
      setNewPassword('');
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create user');
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (u: UserOut) => {
    setError('');
    setNotice('');
    if (!window.confirm(`Delete ${u.email}? This also removes their saved reports.`)) return;
    try {
      await api.deleteUser(u.id);
      setNotice(`Deleted ${u.email}.`);
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete user');
    }
  };

  const handleReset = async (u: UserOut) => {
    setError('');
    setNotice('');
    const pw = window.prompt(`New password for ${u.email} (min 8 chars):`);
    if (pw == null) return;
    if (pw.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    try {
      await api.resetPassword(u.id, pw);
      setNotice(`Password reset for ${u.email}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reset password');
    }
  };

  return (
    <div className="space-y-5">
      <Panel title="Create Account">
        <ErrorLine message={error} />
        {notice && <p className="text-emerald-300 text-xs mb-3">{notice}</p>}
        <form onSubmit={handleCreate} className="flex flex-col sm:flex-row gap-2.5">
          <input
            type="email"
            required
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="new.user@example.com"
            aria-label="New user email"
            className="flex-1 bg-background border border-border  px-4 py-2.5 text-sm text-foreground placeholder-ink-500 focus:outline-none focus:border-primary focus:ring-1 focus:ring-ring/40"
          />
          <input
            type="password"
            required
            minLength={8}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Temp password (≥ 8 chars)"
            aria-label="New user password"
            className="flex-1 bg-background border border-border  px-4 py-2.5 text-sm text-foreground placeholder-ink-500 focus:outline-none focus:border-primary focus:ring-1 focus:ring-ring/40"
          />
          <button
            type="submit"
            disabled={creating}
            className="bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-primary/80 hover:to-teal-400 disabled:from-ink-800 disabled:to-ink-800 disabled:text-muted-foreground text-ink-950 text-sm font-bold px-5 py-2.5  transition-all cursor-pointer disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-emerald-400 whitespace-nowrap"
          >
            {creating ? 'Creating…' : 'Create'}
          </button>
        </form>
        <p className="text-ink-600 text-[11px] mt-2">
          New accounts are analysts. The admin role is reserved for the configured address.
        </p>
      </Panel>

      <Panel title={`All Users (${users.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted-foreground text-[11px] uppercase tracking-wider border-b border-border">
                <th className="py-2 pr-3 font-semibold">Email</th>
                <th className="py-2 px-3 font-semibold">Role</th>
                <th className="py-2 px-3 font-semibold hidden sm:table-cell">Joined</th>
                <th className="py-2 pl-3 font-semibold text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/70">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="py-2.5 pr-3 text-muted-foreground truncate max-w-[240px]" title={u.email}>
                    {u.email}
                    {u.id === me?.id && <span className="text-muted-foreground text-[11px]"> (you)</span>}
                  </td>
                  <td className="py-2.5 px-3"><RoleBadge role={u.role} /></td>
                  <td className="py-2.5 px-3 text-muted-foreground text-[11px] hidden sm:table-cell">{fmtDate(u.created_at)}</td>
                  <td className="py-2.5 pl-3 text-right whitespace-nowrap">
                    <button
                      onClick={() => handleReset(u)}
                      className="text-[11px] text-muted-foreground hover:text-foreground underline mr-3 cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
                    >
                      reset password
                    </button>
                    <button
                      onClick={() => handleDelete(u)}
                      disabled={u.id === me?.id || u.role === 'admin'}
                      title={u.role === 'admin' ? 'The designated admin cannot be deleted' : undefined}
                      className="text-[11px] text-destructive hover:text-rose-300 underline cursor-pointer disabled:text-ink-700 disabled:no-underline disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-rose-400"
                    >
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

/* ─── Reports (read-only) ─── */

function ReportsPanel() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedTitle, setSelectedTitle] = useState('');

  useEffect(() => {
    // Admins receive every user's reports from this endpoint (see research router).
    api.history().then(setReports).catch((e) => setError(e instanceof Error ? e.message : 'Failed to load reports'));
  }, []);

  const open = async (r: ReportSummary) => {
    setError('');
    try {
      const detail = await api.reportDetail(r.id);
      setSelected(detail.report_md);
      setSelectedTitle(`${detail.symbol} · ${detail.query}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to open report');
    }
  };

  return (
    <Panel
      title={`Saved Reports (${reports.length})`}
      action={<span className="text-ink-600 text-[11px]">read-only</span>}
    >
      <ErrorLine message={error} />
      {selected != null ? (
        <div>
          <button
            onClick={() => setSelected(null)}
            className="text-xs text-muted-foreground hover:text-foreground underline mb-3 cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            ← Back to list
          </button>
          <h3 className="text-foreground font-semibold text-sm mb-2">{selectedTitle}</h3>
          <pre className="whitespace-pre-wrap text-muted-foreground text-xs bg-background/60 border border-border  p-4 max-h-[60vh] overflow-auto">
            {selected}
          </pre>
        </div>
      ) : reports.length === 0 ? (
        <p className="text-muted-foreground text-sm">No reports have been generated yet.</p>
      ) : (
        <ul className="divide-y divide-border/70">
          {reports.map((r) => (
            <li key={r.id}>
              <button
                onClick={() => open(r)}
                className="w-full flex items-center justify-between gap-3 py-2.5 text-left hover:bg-muted/40  px-2 -mx-2 transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
              >
                <span className="min-w-0">
                  <span className="block text-sm font-semibold text-muted-foreground">{r.symbol}</span>
                  <span className="block text-[11px] text-muted-foreground truncate">{r.query}</span>
                </span>
                <span className="text-muted-foreground text-[11px] shrink-0">{fmtDate(r.created_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

/* ─── Audit Log ─── */

const AUDIT_ACTIONS = [
  '', 'login', 'login_failed', 'register', 'user_create',
  'user_delete', 'role_change', 'password_reset', 'settings_change',
];
const PAGE_SIZE = 25;

function AuditPanel() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [action, setAction] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api
      .auditLog({ limit: PAGE_SIZE, offset, action: action || undefined })
      .then((r) => { setEntries(r.entries); setTotal(r.total); })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load audit log'));
  }, [offset, action]);

  useEffect(() => { load(); }, [load]);

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Panel
      title="Audit Log"
      action={
        <select
          value={action}
          onChange={(e) => { setAction(e.target.value); setOffset(0); }}
          aria-label="Filter by action"
          className="bg-background border border-border  px-2.5 py-1.5 text-xs text-muted-foreground focus:outline-none focus:border-primary cursor-pointer"
        >
          {AUDIT_ACTIONS.map((a) => (
            <option key={a || 'all'} value={a}>{a || 'all actions'}</option>
          ))}
        </select>
      }
    >
      <ErrorLine message={error} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted-foreground text-[11px] uppercase tracking-wider border-b border-border">
              <th className="py-2 pr-3 font-semibold">When</th>
              <th className="py-2 px-3 font-semibold">Actor</th>
              <th className="py-2 px-3 font-semibold">Action</th>
              <th className="py-2 px-3 font-semibold">Target</th>
              <th className="py-2 pl-3 font-semibold hidden md:table-cell">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/70">
            {entries.map((e) => (
              <tr key={e.id}>
                <td className="py-2.5 pr-3 text-muted-foreground text-[11px] whitespace-nowrap">{fmtDate(e.created_at)}</td>
                <td className="py-2.5 px-3 text-muted-foreground truncate max-w-[180px]" title={e.actor_email}>{e.actor_email || '—'}</td>
                <td className="py-2.5 px-3 text-muted-foreground">{e.action}</td>
                <td className="py-2.5 px-3 text-muted-foreground truncate max-w-[180px]" title={e.detail || e.target}>{e.target || '—'}</td>
                <td className="py-2.5 pl-3 text-ink-600 text-[11px] hidden md:table-cell">{e.ip || '—'}</td>
              </tr>
            ))}
            {entries.length === 0 && (
              <tr><td colSpan={5} className="py-6 text-center text-muted-foreground text-sm">No events match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between mt-4 text-xs text-muted-foreground">
        <span>{total} event{total === 1 ? '' : 's'}</span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={page <= 1}
            className="px-3 py-1.5  border border-border hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            Prev
          </button>
          <span className="tabular-nums">{page} / {pages}</span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={page >= pages}
            className="px-3 py-1.5  border border-border hover:bg-muted disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
          >
            Next
          </button>
        </div>
      </div>
    </Panel>
  );
}

/* ─── Settings ─── */

function SettingsPanel() {
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [saving, setSaving] = useState(false);
  const [timeout, setTimeoutValue] = useState('0');

  useEffect(() => {
    api.getSettings()
      .then((s) => { setSettings(s); setTimeoutValue(String(s.session_timeout_minutes)); })
      .catch((e) => setError(e instanceof Error ? e.message : 'Failed to load settings'));
  }, []);

  const patch = async (updates: Parameters<typeof api.updateSettings>[0]) => {
    setError('');
    setNotice('');
    setSaving(true);
    try {
      const next = await api.updateSettings(updates);
      setSettings(next);
      setTimeoutValue(String(next.session_timeout_minutes));
      setNotice('Settings saved.');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Panel title="System Configuration">
      <ErrorLine message={error} />
      {notice && <p className="text-emerald-300 text-xs mb-3">{notice}</p>}

      {!settings ? (
        <p className="text-muted-foreground text-sm">Loading…</p>
      ) : (
        <div className="space-y-5">
          {/* Registration toggle */}
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-muted-foreground text-sm font-medium">Open self-registration</p>
              <p className="text-muted-foreground text-[11px]">When off, only the configured admin address may sign up.</p>
            </div>
            <button
              role="switch"
              aria-checked={settings.registration_open}
              disabled={saving}
              onClick={() => patch({ registration_open: !settings.registration_open })}
              className={`relative w-11 h-6  transition-colors shrink-0 cursor-pointer disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-emerald-400 ${settings.registration_open ? 'bg-primary' : 'bg-ink-700'}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-5 h-5  bg-white transition-transform ${settings.registration_open ? 'translate-x-5' : ''}`} />
            </button>
          </div>

          {/* Session timeout */}
          <div className="border-t border-border pt-5">
            <p className="text-muted-foreground text-sm font-medium mb-1">Session timeout (minutes)</p>
            <p className="text-muted-foreground text-[11px] mb-2.5">Overrides JWT expiry when &gt; 0. Use 0 to keep the server default.</p>
            <div className="flex gap-2.5">
              <input
                type="number"
                min={0}
                max={10080}
                value={timeout}
                onChange={(e) => setTimeoutValue(e.target.value)}
                className="w-32 bg-background border border-border  px-4 py-2 text-sm text-foreground focus:outline-none focus:border-primary focus:ring-1 focus:ring-ring/40"
              />
              <button
                onClick={() => patch({ session_timeout_minutes: Math.max(0, Math.min(10080, Number(timeout) || 0)) })}
                disabled={saving}
                className="bg-muted hover:bg-muted text-foreground text-sm font-semibold px-4 py-2  transition-colors cursor-pointer disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-emerald-400"
              >
                Save
              </button>
            </div>
          </div>

          <p className="text-ink-600 text-[11px] border-t border-border pt-4">
            Only settings this application actually enforces are shown. Billing, external
            integrations, and dynamic rate-limit policies are intentionally omitted — there is
            nothing here to enforce them.
          </p>
        </div>
      )}
    </Panel>
  );
}

/* ─── Console shell ─── */

export default function AdminConsole({ onExit }: { onExit: () => void }) {
  const { user, logout } = useAuth();
  const [tab, setTab] = useState<Tab>('Overview');

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <header className="border-b border-border/70 bg-background/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 py-3.5 flex justify-between items-center gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8  bg-gradient-to-br from-primary/80 to-primary flex items-center justify-center shrink-0" aria-hidden="true">
              <svg className="w-4 h-4 text-ink-950" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <div className="min-w-0">
              <h1 className="font-display text-base sm:text-lg font-bold tracking-tight text-foreground truncate">
                Admin Console
              </h1>
              <p className="text-muted-foreground text-[11px] hidden sm:block">Manage users, oversight & system configuration</p>
            </div>
          </div>

          <div className="flex items-center gap-2.5 sm:gap-3 shrink-0">
            <button
              onClick={onExit}
              className="text-xs text-muted-foreground hover:text-foreground bg-card hover:bg-muted border border-border px-3 py-2  transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
            >
              Research View
            </button>
            <div className="text-right hidden sm:block">
              <span className="block text-xs text-muted-foreground max-w-[160px] truncate" title={user?.email}>{user?.email}</span>
              <span className="block text-[10px] text-primary/80 uppercase tracking-wider">{user?.role}</span>
            </div>
            <button
              onClick={logout}
              className="text-xs text-muted-foreground hover:text-foreground bg-card hover:bg-muted border border-border px-3 py-2  transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
            >
              Sign Out
            </button>
          </div>
        </div>

        {/* Tabs */}
        <nav className="max-w-6xl mx-auto px-4 sm:px-6 flex gap-1 overflow-x-auto" role="tablist" aria-label="Admin sections">
          {TABS.map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={`px-3.5 py-2.5 text-sm font-semibold border-b-2 transition-colors whitespace-nowrap cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400 ${
                tab === t ? 'border-primary text-foreground' : 'border-transparent text-muted-foreground hover:text-muted-foreground'
              }`}
            >
              {t}
            </button>
          ))}
        </nav>
      </header>

      {/* Content */}
      <main className="max-w-6xl mx-auto px-4 sm:px-6 py-6">
        {tab === 'Overview' && <OverviewPanel />}
        {tab === 'Users' && <UsersPanel />}
        {tab === 'Reports' && <ReportsPanel />}
        {tab === 'Audit Log' && <AuditPanel />}
        {tab === 'Settings' && <SettingsPanel />}
      </main>
    </div>
  );
}
