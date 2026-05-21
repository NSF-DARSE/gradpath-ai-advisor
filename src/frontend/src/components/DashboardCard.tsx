import type { ReactNode } from 'react';

type DashboardCardProps = {
  title: string;
  eyebrow?: string;
  children: ReactNode;
};

export function DashboardCard({ title, eyebrow, children }: DashboardCardProps) {
  return (
    <section className="dashboard-card">
      <div className="dashboard-card__header">
        {eyebrow ? <span className="dashboard-card__eyebrow">{eyebrow}</span> : null}
        <h3>{title}</h3>
      </div>
      <div className="dashboard-card__body">{children}</div>
    </section>
  );
}
