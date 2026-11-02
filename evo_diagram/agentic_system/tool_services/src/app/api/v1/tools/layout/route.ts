import { NextResponse } from 'next/server';
import {
  DEFAULT_MAX_TOOL_BODY_BYTES,
  JsonRequestError,
  readJsonRequest,
} from '@/lib/jsonRequest';
import {
  LayoutInputError,
  computeLayoutPositions,
  parseLayoutRequest,
} from '@/lib/layout';

export async function POST(request: Request) {
  try {
    const result = computeLayoutPositions(
      parseLayoutRequest(
        await readJsonRequest(request, DEFAULT_MAX_TOOL_BODY_BYTES),
      ),
    );
    return NextResponse.json(result);
  } catch (error: any) {
    console.error('[Layout] Error:', error);
    const status = error instanceof JsonRequestError
      ? error.status
      : error instanceof LayoutInputError ? 400 : 500;
    return NextResponse.json({ error: error.message }, { status });
  }
}
