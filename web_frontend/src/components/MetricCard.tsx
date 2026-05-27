type MetricCardProps = {
  label: string;
  value: string | number;
  caption?: string;
};

export function MetricCard({ label, value, caption }: MetricCardProps) {
  return (
    <section className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {caption ? <div className="metric-caption">{caption}</div> : null}
    </section>
  );
}
