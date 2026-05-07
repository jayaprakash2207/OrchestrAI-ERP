import { useEffect, useRef, useState } from "react";

import ProgressBar from "../components/ProgressBar";
import FileDownload from "../components/FileDownload";
import { connectGenerateWebSocket, generateERP, getGenerationDownloadUrl, getGenerationStatus } from "../api/client";

export default function GeneratorPage() {
  const [companyName, setCompanyName] = useState("");
  const [requirements, setRequirements] = useState("");
  const [generationId, setGenerationId] = useState(null);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState("Idle");
  const [logs, setLogs] = useState([]);
  const [files, setFiles] = useState([]);
  const socketRef = useRef(null);

  useEffect(() => {
    if (!generationId) return undefined;
    const socket = connectGenerateWebSocket(generationId);
    socketRef.current = socket;
    socket.onopen = () => socket.send("subscribe");
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      setLogs((current) => [...current, `[${new Date().toLocaleTimeString()}] ${payload.content}`]);
      if (payload.metadata?.progress !== undefined) {
        setProgress(payload.metadata.progress);
      }
      if (payload.content) {
        setCurrentStep(payload.content);
      }
    };
    return () => socket.close();
  }, [generationId]);

  async function handleGenerate() {
    const response = await generateERP({ company_name: companyName, requirements });
    setGenerationId(response.generation_id);
    setLogs((current) => [...current, `[${new Date().toLocaleTimeString()}] Generation started`]);
  }

  async function refreshStatus() {
    if (!generationId) return;
    const status = await getGenerationStatus(generationId);
    setFiles(status.available_files.map((name) => ({ name, size: "generated" })));
    setProgress(status.status === "completed" ? 100 : progress);
  }

  return (
    <main style={{ padding: "2rem", fontFamily: "Georgia, serif" }}>
      <h1>AutoERP Generator</h1>
      <label htmlFor="company-name">Company Name</label>
      <input id="company-name" type="text" value={companyName} onChange={(event) => setCompanyName(event.target.value)} placeholder="Your Company" style={{ display: "block", width: "100%", marginBottom: "1rem" }} />
      <label htmlFor="requirements">Requirements</label>
      <textarea
        id="requirements"
        rows={10}
        value={requirements}
        onChange={(event) => setRequirements(event.target.value)}
        style={{ display: "block", width: "100%", marginBottom: "1rem" }}
        placeholder={"Describe your ERP needs.\n\n5 cost centers: Sales, Ops, Finance, HR, IT\nMulti-currency: USD, EUR, GBP\nApproval workflows for invoices >$10k"}
      />
      <div style={{ display: "flex", gap: "1rem", marginBottom: "1rem" }}>
        <button type="button" onClick={handleGenerate} disabled={!requirements.trim()}>Generate ERP</button>
        <button type="button" onClick={() => { setCompanyName(""); setRequirements(""); setLogs([]); setFiles([]); setProgress(0); setCurrentStep("Idle"); }}>Clear</button>
        <button type="button" onClick={() => setRequirements("5 cost centers: Sales, Ops, Finance, HR, IT\nMulti-currency: USD, EUR, GBP\nApproval workflows for invoices over $10000")}>Load Example</button>
        <button type="button" onClick={refreshStatus} disabled={!generationId}>Refresh Status</button>
      </div>
      <ProgressBar progress={progress} currentStep={currentStep} logs={logs} />
      <FileDownload
        files={files}
        downloadAllUrl={generationId ? getGenerationDownloadUrl(generationId) : null}
      />
    </main>
  );
}
