import { JsonRpcProvider, FetchRequest } from 'ethers';

const DEFAULT_URLS = [
  'https://rpc-pulsechain.g4mm4.io',
  'https://rpc.pulsechain.com',
  'https://pulsechain-rpc.publicnode.com'
];

function rpcUrls(): string[] {
  const env = process.env.PLS_RPC_URLS;
  if (!env) return DEFAULT_URLS;
  return env.split(',').map(s => s.trim()).filter(Boolean);
}

function buildProvider(url: string): JsonRpcProvider {
  const req = new FetchRequest(url);
  req.timeout = 8000;
  return new JsonRpcProvider(req, { chainId: 369, name: 'pulsechain' }, { staticNetwork: true });
}

let primary: JsonRpcProvider | null = null;
export function getProvider(): JsonRpcProvider {
  if (primary) return primary;
  primary = buildProvider(rpcUrls()[0]);
  return primary;
}

export async function callWithFallback<T>(
  fn: (p: JsonRpcProvider) => Promise<T>,
  urls: string[] = rpcUrls()
): Promise<T> {
  let lastErr: unknown;
  for (const url of urls) {
    try {
      return await fn(buildProvider(url));
    } catch (err) {
      lastErr = err;
    }
  }
  throw new Error(`All RPCs failed: ${String(lastErr)}`);
}
