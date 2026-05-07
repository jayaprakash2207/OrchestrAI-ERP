import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ padding: "2rem", fontFamily: "Georgia, serif" }}>
      <h1>AI ERP Platform</h1>
      <p>Build complete ERP systems with AutoERP Generator or operate existing environments with the JD Edwards AI Copilot.</p>
      <div style={{ display: "flex", gap: "1rem", marginTop: "1.5rem" }}>
        <Link href="/generator">Open AutoERP Generator</Link>
        <Link href="/copilot">Open JD Edwards AI Copilot</Link>
        <Link href="/jde-view">Open JD-Style ERP Viewer</Link>
        <Link href="/studio">Open Functional Studio</Link>
      </div>
    </main>
  );
}
