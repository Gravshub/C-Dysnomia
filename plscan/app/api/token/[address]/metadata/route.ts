import { NextResponse } from 'next/server';
import { getAddress } from 'ethers';
import { readTokenMeta } from '@/lib/chain/token-meta';
import { labelFor } from '@/lib/labels';
import { logoUrl, dexscreenerTokenUrl } from '@/lib/external/dexscreener';
import { cacheGetSet } from '@/lib/cache/kv';

export const dynamic = 'force-dynamic';

export async function GET(_req: Request, ctx: { params: { address: string } }) {
  let addr: string;
  try { addr = getAddress(ctx.params.address); }
  catch { return NextResponse.json({ error: 'invalid address' }, { status: 400 }); }

  try {
    const token = await cacheGetSet(`meta:${addr.toLowerCase()}`, 300, () => readTokenMeta(addr));
    return NextResponse.json({
      token,
      label: labelFor(addr),
      logoUrl: logoUrl(addr),
      externalLinks: {
        dexscreener: dexscreenerTokenUrl(addr),
        blockscout:  `https://scan.pulsechain.com/address/${addr}`
      }
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 503 });
  }
}
