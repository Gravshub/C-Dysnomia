import { NextResponse } from 'next/server';
import { getPlsUsd } from '@/lib/pricing/pls-usd';
import { cacheGetSet } from '@/lib/cache/kv';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET() {
  try {
    const plsUsd = await cacheGetSet('pls-usd', 30, () => getPlsUsd());
    return NextResponse.json({ plsUsd, cachedAt: Date.now() }, {
      headers: { 'Cache-Control': 'public, s-maxage=30, stale-while-revalidate=60' }
    });
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 503 });
  }
}
