import React, { useState, useEffect, useRef, useCallback } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

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

/* ─── Helpers ─── */
const API_BASE = 'http://localhost:8000';

function formatLargeNumber(num: number | undefined | null): string {
  if (num == null) return 'N/A';
  if (num >= 1e12) return `$${(num / 1e12).toFixed(2)}T`;
  if (num >= 1e9) return `$${(num / 1e9).toFixed(2)}B`;
  if (num >= 1e6) return `$${(num / 1e6).toFixed(2)}M`;
  return `$${num.toLocaleString()}`;
}

function formatMetric(val: number | undefined | null, suffix = ''): string {
  if (val == null) return 'N/A';
  return `${val.toFixed(2)}${suffix}`;
}

/* ─── MetricCard Component ─── */
function MetricCard({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="bg-slate-950 p-4 rounded-lg border border-slate-800 text-center transition-all hover:border-slate-700 hover:shadow-lg">
      <span className="block text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-1">{label}</span>
      <span className={`text-xl font-extrabold ${accent ? 'text-emerald-400' : 'text-slate-100'}`}>{value}</span>
    </div>
  );
}

/* ─── Skeleton Loader ─── */
function SkeletonCards() {
  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-lg grid grid-cols-2 sm:grid-cols-4 gap-4">
      {[...Array(4)].map((_, i) => (
        <div key={i} className="bg-slate-950 p-4 rounded-lg border border-slate-800">
          <div className="h-3 w-16 mx-auto mb-2 rounded animate-shimmer" />
          <div className="h-6 w-20 mx-auto rounded animate-shimmer" />
        </div>
      ))}
    </div>
  );
}

/* ─── Main Dashboard ─── */
export default function StockAnalystDashboard() {
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const [report, setReport] = useState('');
  const [financials, setFinancials] = useState<FinancialData | null>(null);
  const [resolvedSymbol, setResolvedSymbol] = useState<string>('');
  const [livePrice, setLivePrice] = useState<LivePriceData | null>(null);
  const [wsConnected, setWsConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const sseRef = useRef<EventSource | null>(null);
  const statusEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll status log
  useEffect(() => {
    statusEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [statusLog]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      wsRef.current?.close();
      sseRef.current?.close();
    };
  }, []);

  // ── WebSocket: Live price feed ──
  const connectLiveTicker = useCallback((symbol: string) => {
    if (wsRef.current) {
      wsRef.current.close();
      setWsConnected(false);
    }

    const ws = new WebSocket(`${API_BASE.replace('http', 'ws')}/api/ws/stock/${symbol}`);
    wsRef.current = ws;

    ws.onopen = () => setWsConnected(true);

    ws.onmessage = (event) => {
      try {
        const data: LivePriceData = JSON.parse(event.data);
        if (data.price) setLivePrice(data);
      } catch { /* ignore parse errors */ }
    };

    ws.onclose = () => {
      setWsConnected(false);
      // Auto-reconnect after 3 seconds
      setTimeout(() => {
        if (wsRef.current === ws) connectLiveTicker(symbol);
      }, 3000);
    };

    ws.onerror = () => setWsConnected(false);
  }, []);

  // ── SSE: Stream analysis ──
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    // Reset state
    setLoading(true);
    setReport('');
    setFinancials(null);
    setLivePrice(null);
    setResolvedSymbol('');
    setStatusLog(['Connecting to agent pipeline...']);
    setWsConnected(false);

    // Close previous connections
    sseRef.current?.close();
    wsRef.current?.close();

    const url = `${API_BASE}/api/research/stream?query=${encodeURIComponent(query)}`;
    const eventSource = new EventSource(url);
    sseRef.current = eventSource;

    eventSource.addEventListener('status', (event: MessageEvent) => {
      setStatusLog((prev) => [...prev, event.data]);
    });

    eventSource.addEventListener('data', (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data);
        setFinancials(parsed.financials || null);
        setResolvedSymbol(parsed.symbol || '');
        if (parsed.symbol) connectLiveTicker(parsed.symbol);
      } catch { /* ignore */ }
    });

    eventSource.addEventListener('report_chunk', (event: MessageEvent) => {
      setReport((prev) => prev + event.data);
    });

    eventSource.addEventListener('done', () => {
      setStatusLog((prev) => [...prev, '✅ Analysis complete.']);
      eventSource.close();
      setLoading(false);
    });

    eventSource.addEventListener('error', (event: Event) => {
      const msgEvent = event as MessageEvent;
      setStatusLog((prev) => [...prev, `❌ Error: ${msgEvent?.data || 'Connection lost'}`]);
      eventSource.close();
      setLoading(false);
    });
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-sans">
      {/* ── Header ── */}
      <header className="max-w-7xl mx-auto px-6 py-5 flex justify-between items-center border-b border-slate-800/60">
        <div>
          <h1 className="text-2xl font-extrabold tracking-tight text-emerald-400">
            Multi-Agent Financial Analyst
          </h1>
          <p className="text-slate-500 text-xs mt-0.5">
            Real-time research reports powered by Gemini &amp; Google ADK
          </p>
        </div>

        {/* Live Price Widget */}
        {livePrice && (
          <div className="bg-slate-900/80 border border-slate-800 rounded-lg px-5 py-2.5 text-right animate-fade-in backdrop-blur-sm">
            <div className="flex items-center gap-2 justify-end mb-0.5">
              <span className={`inline-block w-2 h-2 rounded-full ${wsConnected ? 'bg-emerald-400 animate-pulse-dot' : 'bg-red-400'}`} />
              <span className="text-[10px] text-slate-500 uppercase font-bold tracking-wider">
                {resolvedSymbol} • Live
              </span>
            </div>
            <span className="text-2xl font-bold text-emerald-400">
              ${livePrice.price.toFixed(2)}
            </span>
            <div className="text-[9px] text-slate-500 mt-0.5">
              Vol: {livePrice.volume.toLocaleString()} • H: ${livePrice.high.toFixed(2)} • L: ${livePrice.low.toFixed(2)}
            </div>
          </div>
        )}
      </header>

      {/* ── Main Content ── */}
      <main className="max-w-7xl mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-12 gap-6">

        {/* ── Left Panel: Search + Status ── */}
        <div className="lg:col-span-3 space-y-4">
          {/* Search Form */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg">
            <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400 mb-3">Start Research</h2>
            <form onSubmit={handleSearch} className="space-y-3">
              <input
                type="text"
                placeholder="e.g. Analyze Tesla, AAPL valuation"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 rounded-lg px-4 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-emerald-500 transition-colors"
                required
                disabled={loading}
              />
              <button
                type="submit"
                disabled={loading}
                className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold py-2.5 rounded-lg transition-all shadow-md cursor-pointer disabled:cursor-not-allowed"
              >
                {loading ? (
                  <span className="flex items-center justify-center gap-2">
                    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Streaming Analysis...
                  </span>
                ) : 'Analyze Ticker'}
              </button>
            </form>
          </div>

          {/* Pipeline Status Log */}
          {statusLog.length > 0 && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 shadow-lg">
              <h3 className="text-[10px] text-slate-500 uppercase font-bold tracking-wider mb-2">Pipeline Log</h3>
              <div className="max-h-60 overflow-y-auto space-y-1 text-xs">
                {statusLog.map((msg, i) => (
                  <div key={i} className="text-slate-400 animate-fade-in leading-relaxed">
                    <span className="text-slate-600 mr-1">{String(i + 1).padStart(2, '0')}.</span>
                    {msg}
                  </div>
                ))}
                <div ref={statusEndRef} />
              </div>
            </div>
          )}
        </div>

        {/* ── Right Panel: Dashboard + Report ── */}
        <div className="lg:col-span-9 space-y-6">

          {/* Key Metrics Cards */}
          {loading && !financials && <SkeletonCards />}

          {financials && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-lg animate-fade-in">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400">
                  {financials.company_name || resolvedSymbol} — Key Metrics
                </h3>
                {financials.sector && (
                  <span className="text-[10px] bg-slate-800 text-slate-400 px-2 py-1 rounded-full">
                    {financials.sector} • {financials.industry}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
                <MetricCard label="Price" value={financials.current_price ? `$${financials.current_price.toFixed(2)}` : 'N/A'} accent />
                <MetricCard label="Market Cap" value={formatLargeNumber(financials.market_cap)} />
                <MetricCard label="P/E Ratio" value={formatMetric(financials.pe_ratio)} />
                <MetricCard label="P/B Ratio" value={formatMetric(financials.pb_ratio)} />
                <MetricCard label="ROE" value={formatMetric(financials.roe, '%')} accent />
                <MetricCard label="EBITDA Margin" value={formatMetric(financials.ebitda_margin, '%')} accent />
              </div>
            </div>
          )}

          {/* Streaming Report */}
          {report ? (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-lg animate-fade-in">
              <div className="prose-report">
                <Markdown remarkPlugins={[remarkGfm]}>{report}</Markdown>
              </div>
            </div>
          ) : !loading ? (
            <div className="bg-slate-900/30 border border-dashed border-slate-800 rounded-xl p-16 text-center">
              <div className="text-slate-600 text-sm">
                <svg className="w-12 h-12 mx-auto mb-3 text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Enter a stock ticker or company name above to generate a real-time investment research report.
              </div>
            </div>
          ) : null}

          {/* Report streaming skeleton */}
          {loading && !report && financials && (
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-lg">
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
    </div>
  );
}
