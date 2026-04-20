'use client';
import { useRouter } from 'next/navigation';
import { useState, useEffect } from 'react';
import { getAddress } from 'ethers';

const FEATURED = [
  { symbol: 'WPLS', address: '0xA1077a294dDE1B09bB078844df40758a5D0f9a27' },
  { symbol: 'HEX',  address: '0x2b591e99afE9f32eAA6214f7B7629768c40Eeb39' },
  { symbol: 'PLSX', address: '0x95B303987A60C71504D99Aa1b13B4DA07b0790ab' },
  { symbol: 'ATROPA', address: '0xCc78A0acDF847A2C1714D2A925bB4477df5d48a6' },
  { symbol: 'GIBS',   address: '0x66a08aa12da955eb63d7ac121a88b2b210a07b03' }
];
const RECENT_KEY = 'plscan:recent';

export function SearchBar() {
  const router = useRouter();
  const [value, setValue] = useState('');
  const [loading, setLoading] = useState(false);
  const [recent, setRecent] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    try { setRecent(JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')); }
    catch { setRecent([]); }
  }, []);

  const submit = (raw: string) => {
    setError(null);
    try {
      const addr = getAddress(raw.trim());
      setLoading(true);
      const next = [addr, ...recent.filter(a => a.toLowerCase() !== addr.toLowerCase())].slice(0, 5);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      // Always route to /token/; the token page performs LP detection server-side
      // and redirects to /lp/ when appropriate.
      router.push(`/token/${addr}`);
    } catch {
      setError('Not a valid address');
    }
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form onSubmit={(e) => { e.preventDefault(); submit(value); }}>
        <div className={`relative card-surface overflow-hidden ${loading ? 'shadow-glow-strong' : ''}`}>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste a token or LP address (0x…)"
            className="w-full bg-transparent px-5 py-4 text-lg font-mono outline-none placeholder:text-text-tertiary"
            aria-label="Token or LP address"
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
          />
          {loading && <div className="scanner-line absolute bottom-0 left-0 h-0.5 w-full" />}
        </div>
      </form>
      {error && <p className="text-sell text-sm mt-2">{error}</p>}
      <div className="mt-5">
        <p className="text-xs uppercase text-text-tertiary tracking-wider mb-2">Featured</p>
        <div className="flex flex-wrap gap-2">
          {FEATURED.map(t => (
            <button key={t.address}
              onClick={() => submit(t.address)}
              className="px-3 py-1.5 rounded-md card-surface text-sm hover:shadow-glow">
              {t.symbol}
            </button>
          ))}
        </div>
      </div>
      {recent.length > 0 && (
        <div className="mt-4">
          <p className="text-xs uppercase text-text-tertiary tracking-wider mb-2">Recent</p>
          <div className="flex flex-wrap gap-2">
            {recent.map(a => (
              <button key={a} onClick={() => submit(a)}
                className="px-3 py-1.5 rounded-md card-surface text-sm font-mono hover:shadow-glow">
                {a.slice(0, 6)}…{a.slice(-4)}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
