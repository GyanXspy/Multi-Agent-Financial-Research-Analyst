interface MetricCardProps {
  label: string;
  value: string;
  accent?: boolean;
}

export default function MetricCard({ label, value, accent = false }: MetricCardProps) {
  return (
    <div className="bg-background/60 px-4 py-3.5  border border-border transition-colors hover:border-border">
      <span className="block text-[10px] text-muted-foreground uppercase font-semibold tracking-widest mb-1">
        {label}
      </span>
      <span className={`block text-lg font-bold tabular-nums truncate ${accent ? 'text-emerald-300' : 'text-foreground'}`} title={value}>
        {value}
      </span>
    </div>
  );
}
