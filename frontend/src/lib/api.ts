const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export async function getHealth() {
  const response = await fetch(`${API_BASE_URL}/health/`, { cache: "no-store" });

  if (!response.ok) {
    throw new Error("Failed to fetch backend health");
  }

  return response.json();
}
