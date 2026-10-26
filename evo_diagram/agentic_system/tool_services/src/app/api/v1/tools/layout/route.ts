import { NextResponse } from 'next/server';
import {
  LayoutInputError,
  computeLayoutPositions,
  parseLayoutRequest,
} from '@/lib/layout';

export async function POST(request: Request) {
  try {
    const result = computeLayoutPositions(
      parseLayoutRequest(await request.json()),
    );
    return NextResponse.json(result);
  } catch (error: any) {
    console.error('[Layout] Error:', error);
    const status = error instanceof LayoutInputError ? 400 : 500;
    return NextResponse.json({ error: error.message }, { status });
  }
}
