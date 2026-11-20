export function ComingSoon({
  title,
  phase,
  summary,
}: {
  title: string;
  phase: string;
  summary: string;
}) {
  return (
    <section className="max-w-2xl">
      <p className="text-xs uppercase tracking-[0.16em] text-amber-200/80">{phase}</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">{title}</h1>
      <p className="mt-4 text-sm leading-6 text-zinc-400">{summary}</p>
    </section>
  );
}
