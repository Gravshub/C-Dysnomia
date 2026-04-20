import { NextResponse } from 'next/server';
import { getAddress } from 'ethers';
import { fetchTokenHolders } from '@/lib/external/blockscout';
import { detectLpPair } from '@/lib/discovery/lp-detect';
import { labelFor } from '@/lib/labels';
import { rawToHuman } from '@/lib/format';
import { cacheGetSet } from '@/lib/cache/kv';

export const dynamic = 'force-dynamic';

export async function GET(_req: Request, ctx: { params: { address: string } }) {
  let addr: string;
  try { addr = getAddress(ctx.params.address); }
  catch { return NextResponse.json({ error: 'invalid address' }, { status: 400 }); }

  try {
    const payload = await cacheGetSet(`holders:${addr.toLowerCase()}`, 60, async () => {
      const [rows, det] = await Promise.all([
        fetchTokenHolders(addr, { offset: 20 }),
        detectLpPair(addr)
      ]);
      if (!det.isPair) return { holders: [], total: '0' };
      // LP decimals = 18 for V2
      const LP_DECIMALS = 18;
      const rowsDec = rows.map(h => ({
        address: h.address,
        label: labelFor(h.address),
        lpBalance: rawToHuman(h.value, LP_DECIMALS).toString()
      }));
      return { holders: rowsDec };
    });
    return NextResponse.json(payload);
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 503 });
  }
}
