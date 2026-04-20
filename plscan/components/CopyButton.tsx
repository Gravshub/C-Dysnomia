'use client';
import { useState } from 'react';

export function CopyButton({ value, label = 'Copy' }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setDone(true);
        setTimeout(() => setDone(false), 1200);
      }}
      className="text-text-tertiary hover:text-accent-secondary text-xs px-1.5 py-0.5 rounded"
    >
      {done ? '✓' : label}
    </button>
  );
}
