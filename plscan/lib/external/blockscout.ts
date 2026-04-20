/**
 * BlockScout API client for PulseChain (api.scan.pulsechain.com).
 *
 * NOTE on endpoint divergence (verified 2026-04-20):
 *   - The classic v1-compat `?module=account&action=tokentx` endpoint on
 *     PulseChain's BlockScout REQUIRES both `contractaddress` AND `address`
 *     (it rejects with `{status:"0", message:"Query parameter address is
 *     required"}` otherwise). This diverges from Etherscan's contract — we
 *     cannot use it for "all transfers of a given token".
 *   - The v2 endpoint `/api/v2/tokens/{contract}/transfers` works without an
 *     address filter, but returns a different shape:
 *       { items: [{ block_hash, from:{hash}, to:{hash}, tx_hash, timestamp,
 *                   total:{value,decimals}, token:{name,symbol,decimals,...} }],
 *         next_page_params: { block_number, index, limit } }
 *     Critically it does NOT include a per-item `block_number` — we resolve
 *     it by looking up the (small, deduped) set of block hashes via
 *     `/api/v2/blocks/{hash}`.
 *   - The v2 endpoint `/api/v2/tokens/{contract}/holders` works cleanly and
 *     returns `{ items: [{ address:{hash}, value }], next_page_params }`.
 *
 * Strategy: this client uses v2 endpoints under the hood and normalizes the
 * response to the v1 Etherscan-compat shape the plan specifies, so callers
 * get a stable interface regardless of which backend the chain exposes.
 *
 * When `opts.address` is passed to fetchTokenTransfers the v1 endpoint is
 * used instead (which works because address filtering is required there).
 */

const BASE = process.env.BLOCKSCOUT_BASE || 'https://api.scan.pulsechain.com/api';

// Derive v2 base by stripping the trailing `/api` if present.
// e.g. https://api.scan.pulsechain.com/api  → https://api.scan.pulsechain.com/api/v2
function v2Base(): string {
  return BASE.endsWith('/api') ? `${BASE}/v2` : `${BASE.replace(/\/$/, '')}/v2`;
}

export interface TokenTransfer {
  hash: string;
  blockNumber: string;
  timeStamp: string;
  from: string;
  to: string;
  value: string;
  tokenName: string;
  tokenSymbol: string;
  tokenDecimal: string;
  contractAddress: string;
}

export interface TokenHolderRow {
  address: string;
  value: string; // raw balance
}

// ----- internal fetch helpers --------------------------------------------

async function getV1<T>(params: Record<string, string | number>): Promise<T> {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(params).map(([k, v]) => [k, String(v)]))
  );
  const url = `${BASE}?${qs}`;
  const r = await fetch(url, { next: { revalidate: 15 } as RequestInit['next'] });
  if (!r.ok) throw new Error(`BlockScout ${r.status}: ${url}`);
  const body = await r.json();
  if (body.status !== '1' && body.message !== 'OK' && !Array.isArray(body.result)) {
    throw new Error(`BlockScout response: ${JSON.stringify(body).slice(0, 200)}`);
  }
  return body.result as T;
}

async function getV2<T>(path: string, query: Record<string, string | number> = {}): Promise<T> {
  const qs = new URLSearchParams(
    Object.fromEntries(Object.entries(query).map(([k, v]) => [k, String(v)]))
  );
  const url = `${v2Base()}${path}${qs.toString() ? `?${qs}` : ''}`;
  const r = await fetch(url, { next: { revalidate: 15 } as RequestInit['next'] });
  if (!r.ok) throw new Error(`BlockScout v2 ${r.status}: ${url}`);
  return (await r.json()) as T;
}

// ----- block hash → height resolution (cached per call) ------------------

interface BlockV2 { height: number }

async function resolveBlockHeights(hashes: string[]): Promise<Record<string, number>> {
  const uniq = Array.from(new Set(hashes));
  const entries = await Promise.all(
    uniq.map(async (h) => {
      try {
        const b = await getV2<BlockV2>(`/blocks/${h}`);
        return [h, Number(b.height) || 0] as const;
      } catch {
        return [h, 0] as const;
      }
    })
  );
  return Object.fromEntries(entries);
}

// ----- public API --------------------------------------------------------

interface V2TransferItem {
  block_hash: string;
  timestamp: string;
  from: { hash: string };
  to: { hash: string };
  tx_hash: string;
  total: { value: string; decimals: string };
  token: { address: string; name: string; symbol: string; decimals: string };
}

interface V2Paged<T> { items: T[]; next_page_params: unknown }

export async function fetchTokenTransfers(
  token: string,
  opts: { address?: string; page?: number; offset?: number } = {}
): Promise<TokenTransfer[]> {
  const page = opts.page ?? 1;
  const offset = opts.offset ?? 50;

  // If caller pins to a specific address, v1 tokentx works and returns
  // blockNumber directly — preferred path (1 HTTP call, no block lookups).
  if (opts.address) {
    return getV1<TokenTransfer[]>({
      module: 'account',
      action: 'tokentx',
      contractaddress: token,
      address: opts.address,
      page,
      offset,
      sort: 'desc'
    });
  }

  // Otherwise use v2 /tokens/{addr}/transfers and normalize.
  // v2 uses `limit`, not `offset`; it does not use `page` — pagination is
  // cursor-based via next_page_params. We approximate classic paging by
  // requesting `page * limit` items and slicing.
  const limit = Math.min(offset * page, 100); // BlockScout v2 caps at ~50–100
  const body = await getV2<V2Paged<V2TransferItem>>(
    `/tokens/${token}/transfers`,
    { limit: Math.min(limit, 50) }
  );
  const items = body.items ?? [];
  const start = (page - 1) * offset;
  const sliced = items.slice(start, start + offset);
  if (sliced.length === 0) return [];

  // Resolve block heights for the (small, deduped) set of block hashes.
  const heights = await resolveBlockHeights(sliced.map((it) => it.block_hash));

  return sliced.map((it) => {
    const ts = Math.floor(new Date(it.timestamp).getTime() / 1000);
    return {
      hash: it.tx_hash,
      blockNumber: String(heights[it.block_hash] ?? 0),
      timeStamp: String(ts),
      from: it.from?.hash ?? '',
      to: it.to?.hash ?? '',
      value: it.total?.value ?? '0',
      tokenName: it.token?.name ?? '',
      tokenSymbol: it.token?.symbol ?? '',
      tokenDecimal: it.token?.decimals ?? '18',
      contractAddress: it.token?.address ?? token
    };
  });
}

interface V2HolderItem {
  address: { hash: string };
  value: string;
}

export async function fetchTokenHolders(
  token: string,
  opts: { page?: number; offset?: number } = {}
): Promise<TokenHolderRow[]> {
  const offset = opts.offset ?? 20;
  const page = opts.page ?? 1;

  // Try v1 first — it's proven to work on PulseChain BlockScout for holders.
  try {
    const rows = await getV1<TokenHolderRow[]>({
      module: 'token',
      action: 'getTokenHolders',
      contractaddress: token,
      page,
      offset
    });
    if (Array.isArray(rows)) return rows;
  } catch {
    // fall through to v2
  }

  // v2 fallback.
  const body = await getV2<V2Paged<V2HolderItem>>(
    `/tokens/${token}/holders`,
    { limit: Math.min(offset * page, 50) }
  );
  const items = body.items ?? [];
  const start = (page - 1) * offset;
  return items.slice(start, start + offset).map((it) => ({
    address: it.address?.hash ?? '',
    value: it.value ?? '0'
  }));
}
