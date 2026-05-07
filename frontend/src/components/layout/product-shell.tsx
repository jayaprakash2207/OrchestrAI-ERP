import { AutoERPCard } from "@/components/generator/autoerp-card";
import { CopilotCard } from "@/components/copilot/copilot-card";

export function ProductShell() {
  return (
    <main className="hero-shell">
      <section className="hero">
        <p className="eyebrow">AI ERP Platform</p>
        <h1>Build new ERP systems and modernize JD Edwards with one AI control plane.</h1>
        <p className="lead">
          This starter workspace is organized for backend services, orchestration graphs,
          retrieval pipelines, and a modern operator console.
        </p>
      </section>
      <section className="card-grid">
        <AutoERPCard />
        <CopilotCard />
      </section>
    </main>
  );
}
