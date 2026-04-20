import type { ReactNode } from 'react';

interface Props {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Card({ title, action, children, className = '' }: Props) {
  return (
    <section className={`card-surface p-5 shadow-none transition hover:shadow-glow ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between mb-4">
          {title && <h2 className="text-sm uppercase tracking-wider text-text-secondary">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
