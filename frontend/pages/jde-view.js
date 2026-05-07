import { useEffect, useMemo, useRef, useState } from "react";

const STORAGE_KEY = "jde-functional-workflow-v1";

const DEFAULT_NODES = [
  { id: "start", label: "START", kind: "start", x: 80, y: 250, color: "#4cae50" },
  { id: "approve", label: "APPROVE", kind: "decision", x: 285, y: 250, color: "#8c97a0" },
  { id: "update", label: "UPDATE", kind: "task", x: 520, y: 175, color: "#a96b57" },
  { id: "reject", label: "REJECT", kind: "task", x: 520, y: 335, color: "#8c97a0" },
  { id: "accept", label: "ACCEPT", kind: "task", x: 760, y: 250, color: "#8c97a0" },
  { id: "end", label: "END", kind: "end", x: 940, y: 250, color: "#d56db4" },
];

const EDGES = [
  { from: "start", to: "approve" },
  { from: "approve", to: "update", condition: "IFAPPROVE" },
  { from: "approve", to: "reject", condition: "IFREJECT" },
  { from: "update", to: "accept" },
  { from: "reject", to: "accept" },
  { from: "accept", to: "end" },
];

const styles = {
  page: {
    minHeight: "100vh",
    background: "#eef1f4",
    color: "#243242",
    fontFamily: '"Source Sans 3", "Segoe UI", sans-serif',
  },
  topBar: {
    background: "linear-gradient(90deg, #0f3f67 0%, #1e5b89 100%)",
    color: "#f6fbff",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "0.6rem 1rem",
    fontSize: "1.05rem",
    boxShadow: "0 2px 8px rgba(6, 31, 52, 0.35)",
  },
  shell: { padding: "0.9rem" },
  chromeCard: {
    background: "#f7f9fb",
    border: "1px solid #d5dce3",
    borderRadius: "6px",
    overflow: "hidden",
    boxShadow: "0 6px 24px rgba(26, 39, 53, 0.08)",
  },
  breadcrumb: {
    padding: "0.8rem 1rem",
    borderBottom: "1px solid #e4e9ee",
    fontSize: "1rem",
    color: "#3d5870",
  },
  commandRow: {
    padding: "0.75rem 1rem",
    display: "grid",
    gridTemplateColumns: "1.1fr 0.7fr 0.95fr 0.95fr",
    gap: "0.8rem",
    borderBottom: "1px solid #e4e9ee",
    background: "#fbfcfd",
  },
  label: {
    fontSize: "0.75rem",
    textTransform: "uppercase",
    color: "#718193",
    letterSpacing: "0.06em",
  },
  field: {
    marginTop: "0.2rem",
    border: "1px solid #d3dce5",
    borderRadius: "4px",
    background: "white",
    padding: "0.4rem 0.5rem",
    fontWeight: 600,
  },
  bodyGrid: {
    display: "grid",
    gridTemplateColumns: "54px 1fr 360px",
    minHeight: "560px",
  },
  rail: {
    background: "#f0f3f6",
    borderRight: "1px solid #d9e0e7",
    paddingTop: "0.8rem",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: "0.95rem",
  },
  railIcon: {
    width: "28px",
    height: "28px",
    borderRadius: "6px",
    border: "1px solid #c9d2db",
    background: "white",
    display: "grid",
    placeItems: "center",
    color: "#4f677c",
    fontSize: "0.95rem",
  },
  canvas: {
    position: "relative",
    background: "#d7d9dc",
    overflow: "hidden",
  },
  sidePanel: {
    borderLeft: "1px solid #d9e0e7",
    background: "#f9fbfd",
    padding: "1rem",
  },
  sideTitle: {
    fontSize: "2rem",
    color: "#2a435d",
    marginBottom: "0.75rem",
    fontFamily: '"Barlow Semi Condensed", "Source Sans 3", sans-serif',
  },
  switchRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    margin: "0.55rem 0",
    fontSize: "1rem",
  },
  switchPill: (on) => ({
    width: "56px",
    height: "30px",
    borderRadius: "999px",
    background: on ? "#1783cc" : "#9caebb",
    position: "relative",
    boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.12)",
    cursor: "pointer",
  }),
  switchKnob: (on) => ({
    position: "absolute",
    top: "2px",
    left: on ? "28px" : "2px",
    width: "26px",
    height: "26px",
    borderRadius: "999px",
    background: "#f8fbff",
  }),
  node: (selected) => ({
    position: "absolute",
    width: "92px",
    height: "72px",
    borderRadius: "14px",
    border: selected ? "3px solid #136db1" : "2px solid rgba(255,255,255,0.55)",
    color: "#fff",
    fontWeight: 700,
    letterSpacing: "0.03em",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    boxShadow: "0 6px 15px rgba(34, 43, 53, 0.25)",
    userSelect: "none",
    cursor: "grab",
  }),
  miniHeader: {
    marginTop: "0.85rem",
    fontSize: "0.78rem",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
    color: "#667b90",
    marginBottom: "0.4rem",
  },
  input: {
    width: "100%",
    border: "1px solid #bfd0df",
    borderRadius: "4px",
    padding: "0.42rem 0.5rem",
    fontSize: "0.95rem",
    background: "#fff",
  },
  buttonRow: {
    display: "flex",
    gap: "0.5rem",
    flexWrap: "wrap",
    marginTop: "0.5rem",
  },
  btn: {
    border: "1px solid #8fa8bd",
    borderRadius: "4px",
    background: "#edf4fb",
    padding: "0.35rem 0.55rem",
    cursor: "pointer",
    color: "#234866",
    fontWeight: 600,
  },
  status: {
    background: "#fff",
    border: "1px solid #d4dee8",
    borderRadius: "4px",
    marginTop: "0.6rem",
    padding: "0.5rem",
    fontSize: "0.92rem",
    lineHeight: 1.4,
  },
};

function nodeCenter(node) {
  return { x: node.x + 46, y: node.y + 36 };
}

function pickPath(decision) {
  if (decision === "APPROVE") {
    return ["start", "approve", "update", "accept", "end"];
  }
  return ["start", "approve", "reject", "accept", "end"];
}

function requiredApprovals(amount, rules) {
  const apRules = (rules || []).filter((item) => item.document_type === "ap_invoice");
  if (!apRules.length) {
    return 1;
  }
  let best = 1;
  apRules.forEach((rule) => {
    const threshold = Number(rule.amount_threshold || 0);
    const levels = Number(rule.approval_levels_required || 1);
    if (amount >= threshold) {
      best = Math.max(best, levels);
    }
  });
  return best;
}

export default function JDEViewPage() {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState("");
  const [nodes, setNodes] = useState(DEFAULT_NODES);
  const [selectedId, setSelectedId] = useState("approve");
  const [snapToNode, setSnapToNode] = useState(true);
  const [snapToGrid, setSnapToGrid] = useState(true);
  const [decision, setDecision] = useState("APPROVE");
  const [invoiceAmount, setInvoiceAmount] = useState("12000");
  const [activePath, setActivePath] = useState([]);
  const [statusMessage, setStatusMessage] = useState("Workflow loaded.");
  const canvasRef = useRef(null);
  const dragRef = useRef(null);

  async function loadOutput() {
    setError("");
    try {
      const response = await fetch("/api/jde-output");
      if (!response.ok) {
        const err = await response.json().catch(() => ({ message: "Failed to load output" }));
        throw new Error(err.message || "Failed to load output");
      }
      setPayload(await response.json());
    } catch (err) {
      setError(err.message || "Failed to load output");
    }
  }

  useEffect(() => {
    loadOutput();
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed.nodes)) {
          setNodes(parsed.nodes);
        }
        if (typeof parsed.snapToNode === "boolean") {
          setSnapToNode(parsed.snapToNode);
        }
        if (typeof parsed.snapToGrid === "boolean") {
          setSnapToGrid(parsed.snapToGrid);
        }
      }
    } catch {
      setStatusMessage("Could not restore previous workflow state.");
    }
  }, []);

  useEffect(() => {
    function onMove(event) {
      if (!dragRef.current || !canvasRef.current) {
        return;
      }
      const { id, offsetX, offsetY } = dragRef.current;
      const rect = canvasRef.current.getBoundingClientRect();
      let nextX = event.clientX - rect.left - offsetX;
      let nextY = event.clientY - rect.top - offsetY;

      nextX = Math.max(6, Math.min(nextX, rect.width - 98));
      nextY = Math.max(8, Math.min(nextY, rect.height - 80));

      if (snapToGrid) {
        nextX = Math.round(nextX / 10) * 10;
        nextY = Math.round(nextY / 10) * 10;
      }

      if (snapToNode) {
        nodes.forEach((node) => {
          if (node.id !== id) {
            if (Math.abs(node.x - nextX) <= 7) {
              nextX = node.x;
            }
            if (Math.abs(node.y - nextY) <= 7) {
              nextY = node.y;
            }
          }
        });
      }

      setNodes((current) => current.map((node) => (node.id === id ? { ...node, x: nextX, y: nextY } : node)));
    }

    function onUp() {
      if (dragRef.current) {
        dragRef.current = null;
        setStatusMessage("Node position updated.");
      }
    }

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [nodes, snapToGrid, snapToNode]);

  const selected = nodes.find((item) => item.id === selectedId) || null;
  const tableCount = payload?.schema?.tables?.length || 0;
  const ruleCount = payload?.masterData?.approval_rules?.length || 0;

  const edgeLines = EDGES.map((edge) => {
    const from = nodes.find((item) => item.id === edge.from);
    const to = nodes.find((item) => item.id === edge.to);
    if (!from || !to) {
      return null;
    }
    const fromPoint = nodeCenter(from);
    const toPoint = nodeCenter(to);
    const active = activePath.includes(edge.from) && activePath.includes(edge.to);
    return {
      id: `${edge.from}-${edge.to}`,
      x1: fromPoint.x,
      y1: fromPoint.y,
      x2: toPoint.x,
      y2: toPoint.y,
      condition: edge.condition,
      active,
      midX: (fromPoint.x + toPoint.x) / 2,
      midY: (fromPoint.y + toPoint.y) / 2,
    };
  }).filter(Boolean);

  function runSimulation() {
    const amount = Number(invoiceAmount || 0);
    const levels = requiredApprovals(amount, payload?.masterData?.approval_rules || []);
    const path = pickPath(decision);
    setActivePath(path);
    setStatusMessage(`Simulated ${decision} branch for AP invoice ${amount.toFixed(2)} with required approvals: ${levels}`);
  }

  function saveWorkflow() {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ nodes, snapToNode, snapToGrid, updatedAt: new Date().toISOString() })
      );
      setStatusMessage("Workflow saved locally.");
    } catch {
      setStatusMessage("Failed to save workflow state.");
    }
  }

  function resetLayout() {
    setNodes(DEFAULT_NODES);
    setActivePath([]);
    setStatusMessage("Workflow reset to default layout.");
  }

  function exportWorkflow() {
    const data = {
      nodes,
      edges: EDGES,
      decision,
      invoiceAmount,
      generatedFrom: payload?.generationId || null,
      exportedAt: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "jde-workflow-export.json";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
    setStatusMessage("Workflow exported.");
  }

  function updateSelectedLabel(nextValue) {
    setNodes((current) => current.map((node) => (node.id === selectedId ? { ...node, label: nextValue.toUpperCase() } : node)));
  }

  return (
    <main style={styles.page}>
      <div style={styles.topBar}>
        <div>JD Edwards EnterpriseOne Orchestrator Studio</div>
        <div>
          {payload?.schema?.company || "Capital System"} <span style={{ fontSize: "0.85rem", opacity: 0.85 }}>[DV920]</span>
        </div>
      </div>

      <div style={styles.shell}>
        <div style={styles.chromeCard}>
          <div style={styles.breadcrumb}>Home &gt; Workflows &gt; CREDLIMIT</div>

          <div style={styles.commandRow}>
            <div>
              <div style={styles.label}>Name</div>
              <div style={styles.field}>CREDLIMIT</div>
            </div>
            <div>
              <div style={styles.label}>Version</div>
              <div style={styles.field}>1</div>
            </div>
            <div>
              <div style={styles.label}>Product Code</div>
              <div style={styles.field}>03B - Enhanced Accounts Receivable</div>
            </div>
            <div>
              <div style={styles.label}>Status</div>
              <div style={styles.field}>{error ? "Error" : "Unreserved"}</div>
            </div>
          </div>

          <div style={styles.bodyGrid}>
            <aside style={styles.rail}>
              <div style={styles.railIcon}>⚙</div>
              <div style={styles.railIcon}>✶</div>
              <div style={styles.railIcon}>⎇</div>
              <div style={styles.railIcon}>⟳</div>
              <div style={styles.railIcon}>⌘</div>
            </aside>

            <section ref={canvasRef} style={styles.canvas}>
              <svg width="100%" height="100%" style={{ position: "absolute", inset: 0 }}>
                <defs>
                  <marker id="arrow-head" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" fill="#666b70" />
                  </marker>
                </defs>
                {edgeLines.map((line) => (
                  <g key={line.id}>
                    <line
                      x1={line.x1}
                      y1={line.y1}
                      x2={line.x2}
                      y2={line.y2}
                      stroke={line.active ? "#9b2fc7" : "#666b70"}
                      strokeWidth={line.active ? 4 : 3}
                      markerEnd="url(#arrow-head)"
                    />
                    {line.condition ? (
                      <g transform={`translate(${line.midX - 52}, ${line.midY - 18})`}>
                        <rect width="104" height="26" rx="13" fill="#f7f0fb" stroke="#8b0fa2" strokeWidth="2" />
                        <text x="52" y="17" textAnchor="middle" fontSize="12" fill="#6e0a82">{line.condition}</text>
                      </g>
                    ) : null}
                  </g>
                ))}
              </svg>

              {nodes.map((node) => (
                <div
                  key={node.id}
                  style={{
                    ...styles.node(selectedId === node.id),
                    left: `${node.x}px`,
                    top: `${node.y}px`,
                    background: node.color,
                    outline: activePath.includes(node.id) ? "3px solid #9b2fc7" : "none",
                  }}
                  onMouseDown={(event) => {
                    dragRef.current = {
                      id: node.id,
                      offsetX: event.nativeEvent.offsetX,
                      offsetY: event.nativeEvent.offsetY,
                    };
                  }}
                  onClick={() => setSelectedId(node.id)}
                >
                  {node.label}
                </div>
              ))}
            </section>

            <aside style={styles.sidePanel}>
              <div style={styles.sideTitle}>Workflow</div>

              <div style={styles.switchRow}>
                <span>Snap to other task</span>
                <span style={styles.switchPill(snapToNode)} onClick={() => setSnapToNode((value) => !value)}>
                  <span style={styles.switchKnob(snapToNode)} />
                </span>
              </div>

              <div style={styles.switchRow}>
                <span>Snap to grid line</span>
                <span style={styles.switchPill(snapToGrid)} onClick={() => setSnapToGrid((value) => !value)}>
                  <span style={styles.switchKnob(snapToGrid)} />
                </span>
              </div>

              <div style={styles.miniHeader}>Selected Task</div>
              <input
                style={styles.input}
                value={selected?.label || ""}
                onChange={(event) => updateSelectedLabel(event.target.value)}
              />

              <div style={styles.miniHeader}>Simulation</div>
              <select style={styles.input} value={decision} onChange={(event) => setDecision(event.target.value)}>
                <option value="APPROVE">APPROVE</option>
                <option value="REJECT">REJECT</option>
              </select>
              <div style={{ height: "0.45rem" }} />
              <input
                style={styles.input}
                value={invoiceAmount}
                onChange={(event) => setInvoiceAmount(event.target.value)}
                placeholder="AP invoice amount"
              />

              <div style={styles.buttonRow}>
                <button type="button" style={styles.btn} onClick={runSimulation}>Run</button>
                <button type="button" style={styles.btn} onClick={saveWorkflow}>Save</button>
                <button type="button" style={styles.btn} onClick={resetLayout}>Reset</button>
                <button type="button" style={styles.btn} onClick={exportWorkflow}>Export</button>
              </div>

              <div style={styles.status}>{statusMessage}</div>

              <div style={styles.miniHeader}>Live ERP Context</div>
              <div style={styles.status}>
                <div><strong>Generation:</strong> {payload?.generationId || "-"}</div>
                <div><strong>Data Dictionary Tables:</strong> {tableCount}</div>
                <div><strong>Approval Rules:</strong> {ruleCount}</div>
                <div style={{ marginTop: "0.4rem" }}>
                  <button type="button" style={styles.btn} onClick={loadOutput}>Reload ERP Output</button>
                </div>
              </div>
            </aside>
          </div>
        </div>
      </div>
    </main>
  );
}
