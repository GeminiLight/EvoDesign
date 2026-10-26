import { NextResponse } from 'next/server';
import {
  TextWidthInputError,
  measureTextWidth,
  parseTextWidthRequest,
} from '@/lib/textWidth';

export async function POST(request: Request) {
  try {
    const measurement = measureTextWidth(
      parseTextWidthRequest(await request.json()),
    );
    return NextResponse.json(measurement);
  } catch (error: any) {
    console.error('[TextWidth] Error:', error);
    const status = error instanceof TextWidthInputError ? 400 : 500;
    return NextResponse.json(
      { status: 'error', message: error.message },
      { status },
    );
  }
}
