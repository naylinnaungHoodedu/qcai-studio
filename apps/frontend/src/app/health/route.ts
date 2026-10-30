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
      // The commit this image was built from (Dockerfile ARG GIT_SHA), checked by the deployment record (AC-1-7).
      commit: process.env.GIT_SHA ?? "unknown",
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
