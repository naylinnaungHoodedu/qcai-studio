import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const NO_STORE_HEADERS = {
  "Cache-Control": "no-store",
};

export function GET() {
  return NextResponse.json(
    {
      status: "ok",
      app: "QC+AI Studio Frontend",
      environment: process.env.NODE_ENV ?? "development",
    },
    {
      headers: NO_STORE_HEADERS,
    },
  );
}

export function HEAD() {
  return new NextResponse(null, {
    status: 200,
    headers: NO_STORE_HEADERS,
  });
}
