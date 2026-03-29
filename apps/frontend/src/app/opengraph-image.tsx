import { ImageResponse } from "next/og";

export const alt = "QC+AI Studio social preview";
export const size = {
  width: 1200,
  height: 630,
};
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          alignItems: "stretch",
          background:
            "linear-gradient(135deg, #07111c 0%, #10324a 44%, #f3e6cf 100%)",
          color: "#f7f3eb",
          display: "flex",
          flexDirection: "column",
          height: "100%",
          justifyContent: "space-between",
          padding: "56px",
          width: "100%",
        }}
      >
        <div style={{ color: "#f0c36b", fontSize: 30, letterSpacing: 3, textTransform: "uppercase" }}>QC+AI Studio</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 20, maxWidth: 920 }}>
          <div style={{ fontSize: 72, fontWeight: 700, lineHeight: 1.04 }}>
            Quantum computing and AI, taught through real hardware constraints.
          </div>
          <div style={{ color: "#d7dfeb", fontSize: 30, lineHeight: 1.35 }}>
            Graduate-level modules, grounded lesson search, cited Q&amp;A, projects, and guest-mode public previews.
          </div>
        </div>
        <div style={{ color: "#f7f3eb", display: "flex", fontSize: 26, justifyContent: "space-between" }}>
          <span>qantumlearn.academy</span>
          <span>Modules | Lessons | Grounded QA</span>
        </div>
      </div>
    ),
    size,
  );
}
