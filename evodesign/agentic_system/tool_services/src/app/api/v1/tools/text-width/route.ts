import { NextResponse } from 'next/server';
import {
  DEFAULT_MAX_TOOL_BODY_BYTES,
  JsonRequestError,
  readJsonRequest,
} from '@/lib/jsonRequest';
import {
  TextWidthInputError,
  measureTextWidth,
  parseTextWidthRequest,
} from '@/lib/textWidth';

export async function POST(request: Request) {
  try {
    const measurement = measureTextWidth(
      parseTextWidthRequest(
        await readJsonRequest(request, DEFAULT_MAX_TOOL_BODY_BYTES),
      ),
    );
    return NextResponse.json(measurement);
  } catch (error: any) {
    console.error('[TextWidth] Error:', error);
    const status = error instanceof JsonRequestError
      ? error.status
      : error instanceof TextWidthInputError ? 400 : 500;
    return NextResponse.json(
      { status: 'error', message: error.message },
      { status },
    );
  }
}
