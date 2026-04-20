type Props = {
  title: string;
  description: string;
  plannedFor: string;
};

export function ComingSoon({ title, description, plannedFor }: Props) {
  return (
    <div className="jsp-card p-8 text-center">
      <div className="text-xs uppercase tracking-wider text-corp-muted mb-2">
        Pending Corporate Approval
      </div>
      <h2 className="text-xl font-semibold text-corp-accent mb-2">{title}</h2>
      <p className="text-sm text-corp-text max-w-xl mx-auto">{description}</p>
      <div className="mt-4 text-xs text-corp-muted">Scheduled for release {plannedFor}.</div>
    </div>
  );
}
