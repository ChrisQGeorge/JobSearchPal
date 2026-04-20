import { ReactNode } from "react";

type Props = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
};

export function PageShell({ title, subtitle, actions, children }: Props) {
  return (
    <main className="flex-1 min-h-screen p-8 overflow-y-auto">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-corp-text">{title}</h1>
          {subtitle ? (
            <p className="mt-1 text-sm text-corp-muted">{subtitle}</p>
          ) : null}
        </div>
        {actions ? <div className="flex gap-2">{actions}</div> : null}
      </header>
      {children}
    </main>
  );
}
