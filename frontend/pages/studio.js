import { useMemo, useState } from "react";

import { executeCopilot, generateERP, getGenerationDownloadUrl, getGenerationStatus, queryCopilot } from "../api/client";

const wrap = {
  minHeight: "100vh",
  background: "linear-gradient(180deg, #eef4fa 0%, #f8fbff 55%, #ffffff 100%)",
  fontFamily: '"Segoe UI", Tahoma, sans-serif',
  color: "#1f3142",
  padding: "1.2rem",
};

const card = {
  background: "#ffffff",
  border: "1px solid #d6e2ee",
  borderRadius: "10px",
  boxShadow: "0 8px 20px rgba(21, 46, 71, 0.08)",
};

const heading = {
  fontSize: "1.25rem",
  fontWeight: 700,
  color: "#123554",
  marginBottom: "0.45rem",
};

function StepFlow({ title, steps }) {
  return (
    <section style={{ ...card, padding: "0.9rem" }}>
      <div style={heading}>{title}</div>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "0.45rem" }}>
        {steps.map((step, index) => (
          <div key={`${title}-${step}`} style={{ display: "flex", alignItems: "center", gap: "0.45rem" }}>
            <span style={{ border: "1px solid #b9d0e4", background: "#edf6ff", borderRadius: "999px", padding: "0.25rem 0.7rem", fontSize: "0.88rem" }}>
              {step}
            </span>
            {index < steps.length - 1 ? <span style={{ color: "#6d8298" }}>{">"}</span> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function StudioPage() {
  const [tab, setTab] = useState("copilot");

  const [copilotModule, setCopilotModule] = useState("finance");
  const [copilotPrompt, setCopilotPrompt] = useState("Show me all invoices overdue by more than 30 days");
  const [copilotAnswer, setCopilotAnswer] = useState("");
  const [copilotLoading, setCopilotLoading] = useState(false);
  const [autoExecute, setAutoExecute] = useState(false);
  const [executionPlan, setExecutionPlan] = useState(null);
  const [executionResult, setExecutionResult] = useState(null);

  const [companyName, setCompanyName] = useState("Acme Corp");
  const [requirements, setRequirements] = useState(
    "Create a financial ERP with 5 cost centers: Sales, Operations, Finance, HR, IT. Support USD, EUR, GBP. Approval workflows for invoices over 10000. Real-time GL reporting."
  );
  const [generationId, setGenerationId] = useState("");
  const [generationStatus, setGenerationStatus] = useState("");
  const [availableFiles, setAvailableFiles] = useState([]);
  const [generatorLoading, setGeneratorLoading] = useState(false);

  const modules = ["finance", "supply_chain", "manufacturing", "sales", "hr"];

  async function runCopilot() {
    if (!copilotPrompt.trim()) {
      return;
    }
    setCopilotLoading(true);
    setCopilotAnswer("");
    setExecutionPlan(null);
    setExecutionResult(null);
    try {
      const sessionId = `studio-${Date.now()}`;
      const lowered = copilotPrompt.toLowerCase();
      const actionLikePrompt =
        lowered.includes("create po") ||
        lowered.includes("purchase order") ||
        lowered.includes("post invoice") ||
        lowered.includes("journal entry") ||
        lowered.includes("debit") ||
        lowered.includes("credit");

      if (actionLikePrompt) {
        const response = await executeCopilot({
          message: copilotPrompt,
          session_id: sessionId,
          module: copilotModule,
          confirm: autoExecute,
        });
        setCopilotAnswer(response.answer || "No response returned.");
        setExecutionPlan(response.execution_plan || null);
        setExecutionResult(response.result || null);
      } else {
        const response = await queryCopilot({
          message: copilotPrompt,
          session_id: sessionId,
          module: copilotModule,
        });
        setCopilotAnswer(response.answer || "No response returned.");
      }
    } catch (error) {
      setCopilotAnswer(error.message || "Copilot request failed.");
    } finally {
      setCopilotLoading(false);
    }
  }

  async function executePlannedAction() {
    if (!executionPlan) {
      return;
    }
    setCopilotLoading(true);
    try {
      const response = await executeCopilot({
        message: copilotPrompt,
        session_id: `studio-exec-${Date.now()}`,
        module: copilotModule,
        confirm: true,
      });
      setCopilotAnswer(response.answer || "Execution completed.");
      setExecutionPlan(response.execution_plan || null);
      setExecutionResult(response.result || null);
    } catch (error) {
      setCopilotAnswer(error.message || "Execution failed.");
    } finally {
      setCopilotLoading(false);
    }
  }

  async function startGeneration() {
    if (!requirements.trim()) {
      return;
    }
    setGeneratorLoading(true);
    setGenerationStatus("starting");
    setAvailableFiles([]);
    try {
      const response = await generateERP({ company_name: companyName, requirements });
      setGenerationId(response.generation_id || "");
      setGenerationStatus(response.status || "running");
    } catch (error) {
      setGenerationStatus(`failed: ${error.message || "generation request failed"}`);
    } finally {
      setGeneratorLoading(false);
    }
  }

  async function refreshGeneration() {
    if (!generationId) {
      return;
    }
    try {
      const status = await getGenerationStatus(generationId);
      setGenerationStatus(status.status || "unknown");
      setAvailableFiles(status.available_files || []);
    } catch (error) {
      setGenerationStatus(`failed: ${error.message || "status request failed"}`);
    }
  }

  const downloadUrl = useMemo(() => {
    if (!generationId || generationStatus !== "completed") {
      return "";
    }
    return getGenerationDownloadUrl(generationId);
  }, [generationId, generationStatus]);

  return (
    <main style={wrap}>
      <section style={{ ...card, padding: "1rem", marginBottom: "0.9rem" }}>
        <h1 style={{ margin: 0, fontSize: "1.6rem", color: "#0f2f4d" }}>AutoERP Generator and JD Edwards AI Copilot Studio</h1>
        <p style={{ margin: "0.5rem 0 0", color: "#39556f" }}>
          Functional workspace for both systems: ask Copilot in plain English, or generate a full ERP from requirements.
        </p>
        <div style={{ display: "flex", gap: "0.6rem", marginTop: "0.75rem" }}>
          <button type="button" onClick={() => setTab("copilot")} style={{ border: "1px solid #8db2d0", borderRadius: "6px", padding: "0.45rem 0.8rem", background: tab === "copilot" ? "#dcefff" : "#ffffff", cursor: "pointer" }}>
            System 1: JD Edwards AI Copilot
          </button>
          <button type="button" onClick={() => setTab("generator")} style={{ border: "1px solid #8db2d0", borderRadius: "6px", padding: "0.45rem 0.8rem", background: tab === "generator" ? "#dcefff" : "#ffffff", cursor: "pointer" }}>
            System 2: AutoERP Generator
          </button>
        </div>
      </section>

      {tab === "copilot" ? (
        <section style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: "0.8rem" }}>
          <div style={{ ...card, padding: "0.9rem" }}>
            <div style={heading}>JD Edwards AI Copilot</div>
            <p style={{ marginTop: 0 }}>
              Ask questions in plain English, route to specialist agents, and return results from finance, supply chain, manufacturing, sales, or HR.
            </p>

            <StepFlow
              title="How It Works"
              steps={[
                "Question in English",
                "Intent Understanding",
                "Agent Routing",
                "JD Data Query",
                "Reasoning",
                "Report or Action",
              ]}
            />

            <div style={{ marginTop: "0.9rem" }}>
              <label style={{ fontSize: "0.82rem", textTransform: "uppercase", color: "#68839a" }}>Module</label>
              <select value={copilotModule} onChange={(event) => setCopilotModule(event.target.value)} style={{ width: "100%", marginTop: "0.2rem", border: "1px solid #c1d6e8", borderRadius: "5px", padding: "0.5rem" }}>
                {modules.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </div>

            <div style={{ marginTop: "0.6rem" }}>
              <label style={{ fontSize: "0.82rem", textTransform: "uppercase", color: "#68839a" }}>Prompt</label>
              <textarea
                rows={5}
                value={copilotPrompt}
                onChange={(event) => setCopilotPrompt(event.target.value)}
                style={{ width: "100%", marginTop: "0.2rem", border: "1px solid #c1d6e8", borderRadius: "5px", padding: "0.5rem" }}
              />
            </div>

            <div style={{ marginTop: "0.6rem", display: "flex", gap: "0.55rem" }}>
              <button type="button" onClick={runCopilot} disabled={copilotLoading} style={{ border: "1px solid #2f6c9b", borderRadius: "5px", background: "#0f5488", color: "#fff", padding: "0.45rem 0.75rem", cursor: "pointer" }}>
                {copilotLoading ? "Running..." : "Run Copilot"}
              </button>
              <button type="button" onClick={() => setCopilotPrompt("Create a PO for 100 units of SKU123 from ABC Vendor") } style={{ border: "1px solid #9eb8cd", borderRadius: "5px", background: "#ecf4fb", padding: "0.45rem 0.75rem", cursor: "pointer" }}>
                Load Action Example
              </button>
            </div>

            <div style={{ marginTop: "0.5rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <input
                id="auto-execute"
                type="checkbox"
                checked={autoExecute}
                onChange={(event) => setAutoExecute(event.target.checked)}
              />
              <label htmlFor="auto-execute" style={{ color: "#2f5778", fontWeight: 600 }}>
                Auto-execute action prompts in JD Edwards
              </label>
            </div>

            {executionPlan ? (
              <div style={{ ...card, marginTop: "0.75rem", padding: "0.75rem", borderColor: "#cfe0ef", background: "#f6fbff" }}>
                <strong>Execution Plan</strong>
                <div><strong>Action:</strong> {executionPlan.action_type}</div>
                <div><strong>Module:</strong> {executionPlan.module}</div>
                <div><strong>Summary:</strong> {executionPlan.summary}</div>
                <details style={{ marginTop: "0.45rem" }}>
                  <summary style={{ cursor: "pointer" }}>Parsed Payload</summary>
                  <pre style={{ whiteSpace: "pre-wrap", margin: "0.45rem 0 0", fontSize: "0.82rem" }}>{JSON.stringify(executionPlan.parsed_payload || {}, null, 2)}</pre>
                </details>
                <div style={{ marginTop: "0.55rem" }}>
                  <button
                    type="button"
                    onClick={executePlannedAction}
                    disabled={copilotLoading}
                    style={{ border: "1px solid #2f6c9b", borderRadius: "5px", background: "#0f5488", color: "#fff", padding: "0.4rem 0.7rem", cursor: "pointer" }}
                  >
                    Confirm and Execute
                  </button>
                </div>
              </div>
            ) : null}

            {executionResult ? (
              <div style={{ ...card, marginTop: "0.6rem", padding: "0.75rem", borderColor: "#cfe0ef", background: "#f6fbff" }}>
                <strong>Execution Result</strong>
                <pre style={{ whiteSpace: "pre-wrap", margin: "0.45rem 0 0", fontSize: "0.82rem" }}>{JSON.stringify(executionResult, null, 2)}</pre>
              </div>
            ) : null}

            <div style={{ ...card, marginTop: "0.8rem", padding: "0.8rem", borderColor: "#d9e6f1", background: "#f8fbff" }}>
              <strong>Copilot Output</strong>
              <p style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>{copilotAnswer || "No output yet."}</p>
            </div>
          </div>

          <div style={{ ...card, padding: "0.9rem" }}>
            <div style={heading}>Key Capabilities</div>
            <ul style={{ marginTop: "0.3rem", lineHeight: 1.5 }}>
              <li>AP aging, GL balances, trial balance, reconciliation analytics</li>
              <li>Automated actions: create PO, post invoice, post journal entries</li>
              <li>Approval awareness with thresholds and multi-level rules</li>
              <li>Audit-friendly outputs and module-specific recommendations</li>
            </ul>

            <div style={heading}>Example Month-End</div>
            <p>
              Use prompts to fetch AP aging, detect suspense accounts, and post balanced entries. This page executes the same backend endpoints used by your main app.
            </p>
          </div>
        </section>
      ) : (
        <section style={{ display: "grid", gridTemplateColumns: "1.1fr 0.9fr", gap: "0.8rem" }}>
          <div style={{ ...card, padding: "0.9rem" }}>
            <div style={heading}>AutoERP Generator</div>
            <p style={{ marginTop: 0 }}>
              Describe requirements, run a 5-agent pipeline, and receive a generated ERP package with schema, API code, config files, and seed data.
            </p>

            <StepFlow
              title="5-Agent Pipeline"
              steps={[
                "Requirement Parser",
                "Schema Designer",
                "Code Generator",
                "Config Generator",
                "Data Initializer",
              ]}
            />

            <div style={{ marginTop: "0.8rem" }}>
              <label style={{ fontSize: "0.82rem", textTransform: "uppercase", color: "#68839a" }}>Company Name</label>
              <input
                value={companyName}
                onChange={(event) => setCompanyName(event.target.value)}
                style={{ width: "100%", marginTop: "0.2rem", border: "1px solid #c1d6e8", borderRadius: "5px", padding: "0.5rem" }}
              />
            </div>

            <div style={{ marginTop: "0.6rem" }}>
              <label style={{ fontSize: "0.82rem", textTransform: "uppercase", color: "#68839a" }}>Requirements</label>
              <textarea
                rows={8}
                value={requirements}
                onChange={(event) => setRequirements(event.target.value)}
                style={{ width: "100%", marginTop: "0.2rem", border: "1px solid #c1d6e8", borderRadius: "5px", padding: "0.5rem" }}
              />
            </div>

            <div style={{ marginTop: "0.6rem", display: "flex", gap: "0.55rem", flexWrap: "wrap" }}>
              <button type="button" onClick={startGeneration} disabled={generatorLoading} style={{ border: "1px solid #2f6c9b", borderRadius: "5px", background: "#0f5488", color: "#fff", padding: "0.45rem 0.75rem", cursor: "pointer" }}>
                {generatorLoading ? "Starting..." : "Generate ERP"}
              </button>
              <button type="button" onClick={refreshGeneration} disabled={!generationId} style={{ border: "1px solid #9eb8cd", borderRadius: "5px", background: "#ecf4fb", padding: "0.45rem 0.75rem", cursor: "pointer" }}>
                Refresh Status
              </button>
              {downloadUrl ? (
                <a href={downloadUrl} style={{ border: "1px solid #5f8bb0", borderRadius: "5px", background: "#dbecfb", padding: "0.45rem 0.75rem", textDecoration: "none", color: "#18496d", fontWeight: 600 }}>
                  Download ERP Zip
                </a>
              ) : null}
            </div>

            <div style={{ ...card, marginTop: "0.8rem", padding: "0.8rem", borderColor: "#d9e6f1", background: "#f8fbff" }}>
              <div><strong>Generation ID:</strong> {generationId || "-"}</div>
              <div><strong>Status:</strong> {generationStatus || "-"}</div>
              <div style={{ marginTop: "0.45rem" }}><strong>Available Files:</strong></div>
              <ul style={{ marginTop: "0.35rem" }}>
                {availableFiles.length ? availableFiles.map((name) => <li key={name}>{name}</li>) : <li>No files yet.</li>}
              </ul>
            </div>
          </div>

          <div style={{ ...card, padding: "0.9rem" }}>
            <div style={heading}>What You Get</div>
            <ul style={{ marginTop: "0.3rem", lineHeight: 1.5 }}>
              <li>ERP database schema with GL, AP/AR, master data, approval workflow, audit log</li>
              <li>Ready API endpoints for accounts, invoices, journal posting, reports</li>
              <li>Deployment artifacts: Dockerfile, compose, env template, setup scripts</li>
              <li>Preloaded starter data: chart of accounts, currencies, cost centers</li>
            </ul>

            <div style={heading}>Business Fit</div>
            <p>
              This lets you spin up a dedicated ERP instance quickly for startups, new divisions, or special business units while preserving approvals and audit structure.
            </p>
          </div>
        </section>
      )}
    </main>
  );
}
