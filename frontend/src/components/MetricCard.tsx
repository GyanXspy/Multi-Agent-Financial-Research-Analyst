interface MetricCardProps {
  label: string;
  value: string;
  accent?: boolean;
}

export default function MetricCard({ label, value, accent = false }: MetricCardProps) {
  return (
    <div className="bg-ink-950/60 px-4 py-3.5 rounded-xl border border-ink-800 transition-colors hover:border-ink-700">
      <span className="block text-[10px] text-ink-400 uppercase font-semibold tracking-widest mb-1">
        {label}
      </span>
      <span className={`block text-lg font-bold tabular-nums truncate ${accent ? 'text-emerald-300' : 'text-white'}`} title={value}>
        {value}
      </span>
    </div>
  );
}
