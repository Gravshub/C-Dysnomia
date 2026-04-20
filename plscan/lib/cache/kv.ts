// Vercel KV when env vars are set; otherwise in-memory.
// Both paths return the decoded value.
interface Entry<T> { value: T; expiresAt: number; }
const memory = new Map<string, Entry<unknown>>();

const KV_URL = process.env.KV_REST_API_URL;
const KV_TOKEN = process.env.KV_REST_API_TOKEN;

async function kvGet<T>(key: string): Promise<T | null> {
  if (!KV_URL || !KV_TOKEN) {
    const e = memory.get(key) as Entry<T> | undefined;
    if (!e) return null;
    if (Date.now() > e.expiresAt) { memory.delete(key); return null; }
    return e.value;
  }
  const r = await fetch(`${KV_URL}/get/${encodeURIComponent(key)}`, {
    headers: { Authorization: `Bearer ${KV_TOKEN}` }
  });
  if (!r.ok) return null;
  const j = await r.json();
  if (j.result == null) return null;
  try { return JSON.parse(j.result) as T; } catch { return null; }
}

async function kvSet<T>(key: string, value: T, ttlSec: number): Promise<void> {
  if (!KV_URL || !KV_TOKEN) {
    memory.set(key, { value, expiresAt: Date.now() + ttlSec * 1000 });
    return;
  }
  await fetch(`${KV_URL}/set/${encodeURIComponent(key)}?EX=${Math.max(1, Math.floor(ttlSec))}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${KV_TOKEN}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(value)
  });
}

export async function cacheGetSet<T>(
  key: string, ttlSec: number, compute: () => Promise<T>
): Promise<T> {
  const hit = await kvGet<T>(key);
  if (hit !== null && hit !== undefined) return hit;
  const fresh = await compute();
  await kvSet<T>(key, fresh, ttlSec);
  return fresh;
}
