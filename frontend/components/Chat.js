import { useEffect, useRef, useState } from "react";

import { connectChatWebSocket, queryCopilot } from "../api/client";

export default function Chat({ mode = "copilot" }) {
  const [messages, setMessages] = useState([
    { role: "assistant", content: `Welcome to the ${mode === "copilot" ? "JD Edwards AI Copilot" : "assistant"}.` }
  ]);
  const [input, setInput] = useState("");
  const [module, setModule] = useState("Finance");
  const [sessionId] = useState(() => `session-${Date.now()}`);
  const [loading, setLoading] = useState(false);
  const socketRef = useRef(null);

  useEffect(() => {
    const socket = connectChatWebSocket(sessionId);
    socketRef.current = socket;
    socket.onopen = () => socket.send("subscribe");
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "message") {
        setMessages((current) => {
          const next = [...current];
          const last = next[next.length - 1];
          if (last && last.role === "assistant" && loading) {
            next[next.length - 1] = { role: "assistant", content: payload.content };
            return next;
          }
          return [...next, { role: "assistant", content: payload.content }];
        });
      }
    };
    return () => socket.close();
  }, [sessionId, loading]);

  async function handleSend() {
    if (!input.trim()) return;
    const prompt = input;
    setMessages((current) => [...current, { role: "user", content: prompt }]);
    setInput("");
    setLoading(true);
    try {
      const response = await queryCopilot({
        message: prompt,
        session_id: sessionId,
        module: module.toLowerCase().replace(" ", "_")
      });
      setMessages((current) => [...current, { role: "assistant", content: response.answer }]);
    } catch (error) {
      setMessages((current) => [...current, { role: "assistant", content: error.message }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main style={{ display: "grid", gridTemplateColumns: "280px 1fr", minHeight: "100vh" }}>
      <aside style={{ borderRight: "1px solid #ddd", padding: "1rem" }}>
        <h2>Modules</h2>
        {["Finance", "Supply Chain", "Manufacturing", "Sales", "HR"].map((item) => (
          <button key={item} type="button" onClick={() => setModule(item)} style={{ display: "block", width: "100%", marginBottom: ".5rem" }}>
            {item} {module === item ? "(Active)" : ""}
          </button>
        ))}
        <h3>Quick Actions</h3>
        <button type="button">Show AP Aging</button>
        <button type="button">Create PO</button>
        <button type="button">View GL Accounts</button>
      </aside>
      <section style={{ padding: "1rem" }}>
        <h1>JD Edwards AI Copilot</h1>
        <div style={{ minHeight: "60vh", border: "1px solid #ddd", padding: "1rem", marginBottom: "1rem" }}>
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} style={{ marginBottom: ".75rem" }}>
              <strong>{message.role === "user" ? "You" : "Assistant"}:</strong> {message.content}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: ".5rem" }}>
          <input value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask a question..." style={{ flex: 1 }} />
          <button type="button" onClick={handleSend} disabled={loading}>{loading ? "Sending..." : "Send"}</button>
          <button type="button" onClick={() => setMessages([])}>Clear</button>
        </div>
      </section>
    </main>
  );
}
