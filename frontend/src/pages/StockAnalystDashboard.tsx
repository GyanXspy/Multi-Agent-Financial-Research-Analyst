/**
 * StockAnalystDashboard — the main research console.
 *
 * Streams the multi-agent pipeline over authenticated SSE, shows live prices
 * via WebSocket, renders metrics, a 1-year price chart, the streaming
 * markdown report, past report history, and (for admins) user management.
 */

import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

import { api, getToken, API_BASE, WS_BASE } from '../lib/api';
import type { ReportSummary, UserOut } from '../lib/api';
import { connectSSE } from '../lib/sse';
import { useAuth } from '../context/AuthContext';

import MetricCard from '../components/MetricCard';
import PriceChart from '../components/PriceChart';
import PipelineStatus from '../components/PipelineStatus';
import { INITIAL_AGENTS, reduceAgentStates } from '../lib/pipeline';
import type { PipelineAgents } from '../lib/pipeline';
// Lazy-loaded: react-markdown + remark-gfm are heavy and only needed once a report exists
const ReportView = lazy(() => import('../components/ReportView'));

/* ─── Types ─── */
interface FinancialData {
  company_name?: string;
  current_price?: number;
  currency?: string;
  market_cap?: number;
  pe_ratio?: number;
  pb_ratio?: number;
  ev_ebitda?: number;
  roe?: number;
  ebitda_margin?: number;
  revenue?: number;
  net_income?: number;
  eps?: number;
  sector?: string;
  industry?: string;
  price_history_1y?: number[];
  price_history_dates?: string[];
}

interface LivePriceData {
  symbol: string;
  price: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  timestamp: string;
  error?: string;
}

/* ─── Formatting helpers ─── */
function formatLargeNumber(num: number | undefined | null, symbol = '$'): string {
  if (num == null) return 'N/A';
  if (num >= 1e12) return `${symbol}${(num / 1e12).toFixed(2)}T`;
  if (num >= 1e9) return `${symbol}${(num / 1e9).toFixed(2)}B`;
  if (num >= 1e6) return `${symbol}${(num / 1e6).toFixed(2)}M`;
  return `${symbol}${num.toLocaleString()}`;
}

function formatMetric(val: number | undefined | null, suffix = ''): string {
  if (val == null) return 'N/A';
  return `${val.toFixed(2)}${suffix}`;
}

/* ─── Skeleton loader ─── */
function SkeletonCards() {
  return (
    <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 shadow-lg grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3" aria-hidden="true">
      {[...Array(6)].map((_, i) => (
        <div key={i} className="bg-ink-950/60 px-4 py-3.5 rounded-xl border border-ink-800">
          <div className="h-2.5 w-14 mb-2 rounded animate-shimmer" />
          <div className="h-5 w-20 rounded animate-shimmer" />
        </div>
      ))}
    </div>
  );
}

/* ─── Admin users panel ─── */
function AdminPanel() {
  const { user } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api.listUsers().then((r) => setUsers(r.users)).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const toggleRole = async (u: UserOut) => {
    try {
      await api.updateRole(u.id, u.role === 'admin' ? 'analyst' : 'admin');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Role update failed');
    }
  };

  return (
    <div className="bg-ink-900 border border-ink-800 rounded-2xl shadow-lg overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-5 py-3.5 text-xs font-semibold uppercase tracking-widest text-ink-400 hover:text-white transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
      >
        User Management
        <svg className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {open && (
        <div className="px-5 pb-4 space-y-2">
          {error && <p role="alert" className="text-rose-300 text-xs">{error}</p>}
          {users.map((u) => (
            <div key={u.id} className="flex items-center justify-between gap-2 text-sm">
              <span className="text-ink-300 truncate" title={u.email}>{u.email}</span>
              <div className="flex items-center gap-2 shrink-0">
                <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${u.role === 'admin' ? 'bg-emerald-500/15 text-emerald-300' : 'bg-ink-800 text-ink-400'}`}>
                  {u.role}
                </span>
                {u.id !== user?.id && (
                  <button
                    onClick={() => toggleRole(u)}
                    className="text-[10px] text-ink-400 hover:text-white underline cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
                  >
                    {u.role === 'admin' ? 'demote' : 'promote'}
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ─── Main Dashboard ─── */
export default function StockAnalystDashboard() {
  const { user, logout } = useAuth();

  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [agents, setAgents] = useState<PipelineAgents>(INITIAL_AGENTS);
  const [report, setReport] = useState('');
  const [financials, setFinancials] = useState<FinancialData | null>(null);
  const [resolvedSymbol, setResolvedSymbol] = useState('');
  const [livePrice, setLivePrice] = useState<LivePriceData | null>(null);
  const [wsConnected, setWsConnected] = useState(false);
  const [pipelineError, setPipelineError] = useState('');
  const [history, setHistory] = useState<ReportSummary[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const sseAbortRef = useRef<(() => void) | null>(null);

  const refreshHistory = useCallback(() => {
    api.history().then(setHistory).catch(() => { /* non-fatal */ });
  }, []);

  useEffect(() => {
    refreshHistory();
    return () => {
      wsRef.current?.close();
      sseAbortRef.current?.();
    };
  }, [refreshHistory]);

  /* ── WebSocket: live price feed ── */
  const connectLiveTicker = useCallback((symbol: string) => {
    wsRef.current?.close();
    setWsConnected(false);

    const token = getToken();
    if (!token) return;

    const ws = new WebSocket(`${WS_BASE}/api/ws/stock/${encodeURIComponent(symbol)}?token=${encodeURIComponent(token)}`);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);
    ws.onmessage = (event) => {
      try {
        const data: LivePriceData = JSON.parse(event.data);
        if (data.price) setLivePrice(data);
      } catch { /* ignore parse errors */ }
    };
    ws.onclose = (event) => {
      setWsConnected(false);
      // Auto-reconnect unless auth was rejected or a newer socket took over
      if (event.code !== 4401 && event.code !== 4400) {
        setTimeout(() => {
          if (wsRef.current === ws) connectLiveTicker(symbol);
        }, 5000);
      }
    };
    ws.onerror = () => setWsConnected(false);
  }, []);

  /* ── SSE: stream analysis ── */
  const handleSearch = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || loading) return;

    // Reset state
    setLoading(true);
    setReport('');
    setFinancials(null);
    setLivePrice(null);
    setResolvedSymbol('');
    setPipelineError('');
    setAgents(INITIAL_AGENTS);
    setStatusLog(['Connecting to agent pipeline…']);
    setWsConnected(false);

    sseAbortRef.current?.();
    wsRef.current?.close();

    const token = getToken();
    if (!token) {
      setPipelineError('Session expired. Please sign in again.');
      setLoading(false);
      return;
    }

    const url = `${API_BASE}/api/research/stream?query=${encodeURIComponent(trimmed)}`;
    sseAbortRef.current = connectSSE(url, token, {
      onEvent: (event, data) => {
        switch (event) {
          case 'status':
            setStatusLog((prev) => [...prev, data]);
            setAgents((prev) => reduceAgentStates(prev, data));
            if (data.includes('Analysis complete')) {
              setLoading(false);
              refreshHistory();
            }
            break;
          case 'data':
            try {
              const parsed = JSON.parse(data);
              setFinancials(parsed.financials || null);
              setResolvedSymbol(parsed.symbol || '');
              if (parsed.symbol) connectLiveTicker(parsed.symbol);
            } catch { /* ignore */ }
            break;
          case 'report_chunk':
            setReport((prev) => prev + data);
            break;
          case 'done':
            setLoading(false);
            sseAbortRef.current?.();
            refreshHistory();
            break;
          case 'error':
            setPipelineError(data || 'Analysis failed.');
            setLoading(false);
            sseAbortRef.current?.();
            break;
        }
      },
      onError: (message) => {
        setPipelineError(message);
        setLoading(false);
      },
      onClose: () => setLoading(false),
    });
  };

  /* ── Load a stored report from history ── */
  const loadHistoryReport = async (id: number) => {
    if (loading) return;
    try {
      const detail = await api.reportDetail(id);
      setReport(detail.report_md);
      setResolvedSymbol(detail.symbol);
      setPipelineError('');
      setStatusLog([]);
      setAgents(INITIAL_AGENTS);
      try {
        const data = JSON.parse(detail.data_json);
        setFinancials(data.financials || null);
        if (detail.symbol) connectLiveTicker(detail.symbol);
      } catch {
        setFinancials(null);
      }
    } catch (e) {
      setPipelineError(e instanceof Error ? e.message : 'Failed to load report');
    }
  };

  const currencySymbol = financials?.currency === 'INR' ? '₹' : '$';

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100">
      {/* ── Header ── */}
      <header className="border-b border-ink-800/70 bg-ink-950/80 backdrop-blur sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3.5 flex justify-between items-center gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-400 to-teal-600 flex items-center justify-center shrink-0" aria-hidden="true">
              <svg className="w-4 h-4 text-ink-950" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 17l6-6 4 4 8-8M15 7h6v6" />
              </svg>
            </div>
            <div className="min-w-0">
              <h1 className="font-display text-base sm:text-lg font-bold tracking-tight text-white truncate">
                Multi-Agent Financial Analyst
              </h1>
              <p className="text-ink-500 text-[11px] hidden sm:block">
                Real-time AI equity research · Gemini powered
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 sm:gap-4 shrink-0">
            {/* Live price widget */}
            {livePrice && (
              <div className="hidden md:block bg-ink-900/80 border border-ink-800 rounded-xl px-4 py-2 text-right animate-fade-in">
                <div className="flex items-center gap-1.5 justify-end mb-0.5">
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full ${wsConnected ? 'bg-emerald-400 animate-pulse-dot' : 'bg-rose-400'}`}
                    role="status"
                    aria-label={wsConnected ? 'Live feed connected' : 'Live feed disconnected'}
                  />
                  <span className="text-[10px] text-ink-500 uppercase font-semibold tracking-wider">
                    {resolvedSymbol} · Live
                  </span>
                </div>
                <span className="text-lg font-bold text-emerald-300 tabular-nums">
                  {currencySymbol}{livePrice.price.toFixed(2)}
                </span>
                <div className="text-[9px] text-ink-500 tabular-nums">
                  H {currencySymbol}{livePrice.high.toFixed(2)} · L {currencySymbol}{livePrice.low.toFixed(2)} · Vol {livePrice.volume.toLocaleString()}
                </div>
              </div>
            )}

            {/* User menu */}
            <div className="flex items-center gap-2.5">
              <div className="text-right hidden sm:block">
                <span className="block text-xs text-ink-300 max-w-[160px] truncate" title={user?.email}>{user?.email}</span>
                <span className="block text-[10px] text-emerald-400/80 uppercase tracking-wider">{user?.role}</span>
              </div>
              <button
                onClick={logout}
                className="text-xs text-ink-400 hover:text-white bg-ink-900 hover:bg-ink-800 border border-ink-800 px-3 py-2 rounded-xl transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-emerald-400"
              >
                Sign Out
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* ── Main Content ── */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* ── Left Panel ── */}
        <div className="lg:col-span-3 space-y-4">
          {/* Search form */}
          <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 shadow-lg">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-ink-400 mb-3">
              Start Research
            </h2>
            <form onSubmit={handleSearch} className="space-y-3">
              <label htmlFor="query" className="sr-only">Company name or ticker symbol</label>
              <input
                id="query"
                type="text"
                placeholder="e.g. Analyze Tesla, AAPL…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                maxLength={200}
                className="w-full bg-ink-950 border border-ink-700 rounded-xl px-4 py-2.5 text-sm text-white placeholder-ink-500 focus:outline-none focus:border-emerald-400 focus:ring-1 focus:ring-emerald-400/40 transition-colors"
                required
                disabled={loading}
              />
              <button
                type="submit"
                disabled={loading || !query.trim()}
                className="w-full bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-400 hover:to-teal-400 disabled:from-ink-800 disabled:to-ink-800 disabled:text-ink-500 text-ink-950 text-sm font-bold py-2.5 rounded-xl transition-all shadow-md shadow-emerald-500/10 disabled:shadow-none cursor-pointer disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="w-3.5 h-3.5 rounded-full border-2 border-ink-950/30 border-t-ink-950 animate-spin" aria-hidden="true" />
                    Analyzing…
                  </span>
                ) : 'Analyze'}
              </button>
            </form>

            {pipelineError && (
              <div role="alert" className="mt-3 bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs rounded-xl px-3.5 py-2.5">
                {pipelineError}
              </div>
            )}
          </div>

          {/* Pipeline status */}
          {(loading || statusLog.length > 0) && (
            <PipelineStatus agents={agents} log={statusLog} />
          )}

          {/* History */}
          {history.length > 0 && (
            <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 shadow-lg">
              <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-400 mb-3">
                Recent Reports
              </h3>
              <ul className="space-y-1.5">
                {history.slice(0, 8).map((r) => (
                  <li key={r.id}>
                    <button
                      onClick={() => loadHistoryReport(r.id)}
                      disabled={loading}
                      className="w-full text-left px-3 py-2 rounded-xl hover:bg-ink-800/70 transition-colors cursor-pointer disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-emerald-400 group"
                    >
                      <span className="block text-sm font-semibold text-ink-200 group-hover:text-white">{r.symbol}</span>
                      <span className="block text-[11px] text-ink-500 truncate">
                        {r.query} · {new Date(r.created_at + 'Z').toLocaleDateString()}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Admin panel */}
          {user?.role === 'admin' && <AdminPanel />}
        </div>

        {/* ── Right Panel ── */}
        <div className="lg:col-span-9 space-y-5">
          {/* Metrics */}
          {loading && !financials && <SkeletonCards />}

          {financials && (
            <div className="bg-ink-900 border border-ink-800 rounded-2xl p-5 shadow-lg animate-fade-in">
              <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-ink-400">
                  {financials.company_name || resolvedSymbol} — Key Metrics
                </h3>
                {financials.sector && (
                  <span className="text-[10px] bg-ink-800 text-ink-400 px-2.5 py-1 rounded-full">
                    {financials.sector}{financials.industry ? ` · ${financials.industry}` : ''}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                <MetricCard label="Price" value={financials.current_price != null ? `${currencySymbol}${financials.current_price.toFixed(2)}` : 'N/A'} accent />
                <MetricCard label="Market Cap" value={formatLargeNumber(financials.market_cap, currencySymbol)} />
                <MetricCard label="P/E Ratio" value={formatMetric(financials.pe_ratio)} />
                <MetricCard label="P/B Ratio" value={formatMetric(financials.pb_ratio)} />
                <MetricCard label="ROE" value={formatMetric(financials.roe, '%')} accent />
                <MetricCard label="EBITDA Margin" value={formatMetric(financials.ebitda_margin, '%')} accent />
              </div>
            </div>
          )}

          {/* Price chart */}
          {financials?.price_history_1y && financials.price_history_1y.length > 1 && (
            <PriceChart
              prices={financials.price_history_1y}
              dates={financials.price_history_dates}
              currency={financials.currency}
            />
          )}

          {/* Report */}
          {report ? (
            <Suspense
              fallback={
                <div className="bg-ink-900 border border-ink-800 rounded-2xl p-8 shadow-lg" aria-hidden="true">
                  <div className="h-6 w-1/2 rounded animate-shimmer" />
                </div>
              }
            >
              <ReportView report={report} symbol={resolvedSymbol} streaming={loading} />
            </Suspense>
          ) : !loading ? (
            <div className="bg-ink-900/40 border border-dashed border-ink-800 rounded-2xl px-8 py-16 text-center">
              <svg className="w-12 h-12 mx-auto mb-4 text-ink-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <p className="text-ink-400 text-sm max-w-md mx-auto">
                Enter a stock ticker or company name to generate a real-time, AI-assembled investment research report.
              </p>
              <p className="text-ink-600 text-xs mt-2">
                Try “Analyze Apple”, “TSLA valuation”, or “Reliance Industries”.
              </p>
            </div>
          ) : null}

          {/* Report streaming skeleton */}
          {loading && !report && financials && (
            <div className="bg-ink-900 border border-ink-800 rounded-2xl p-8 shadow-lg" aria-hidden="true">
              <div className="space-y-3">
                <div className="h-6 w-3/4 rounded animate-shimmer" />
                <div className="h-4 w-full rounded animate-shimmer" />
                <div className="h-4 w-5/6 rounded animate-shimmer" />
                <div className="h-4 w-4/5 rounded animate-shimmer" />
                <div className="h-4 w-2/3 rounded animate-shimmer" />
              </div>
            </div>
          )}
        </div>
      </main>

      <footer className="max-w-7xl mx-auto px-6 pb-6 text-center">
        <p className="text-ink-600 text-[11px]">
          AI-generated research for informational purposes only — not investment advice.
        </p>
      </footer>
    </div>
  );
}
