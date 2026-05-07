const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {})
    },
    ...options
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ message: "Request failed" }));
    throw new Error(error.message || "Request failed");
  }

  return response.json();
}

export function queryCopilot(payload, token) {
  return request("/api/copilot/chat", {
    method: "POST",
    body: JSON.stringify(payload),
    token
  });
}

export function executeCopilot(payload, token) {
  return request("/api/copilot/execute", {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export function generateERP(payload, token) {
  return request("/api/autoerp/generate", {
    method: "POST",
    body: JSON.stringify(payload),
    token
  });
}

export function getGenerationStatus(generationId, token) {
  return request(`/api/autoerp/generate/${generationId}`, { token });
}

export function getGenerationDownloadUrl(generationId) {
  return `${API_BASE_URL}/api/autoerp/generate/${generationId}/download`;
}

export function connectChatWebSocket(sessionId) {
  return new WebSocket(`ws://localhost:8000/ws/chat/${sessionId}`);
}

export function connectGenerateWebSocket(generationId) {
  return new WebSocket(`ws://localhost:8000/ws/generate/${generationId}`);
}
