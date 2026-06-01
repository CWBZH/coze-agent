export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

async function buildApiError(method: string, path: string, response: Response) {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (payload && typeof payload === "object") {
    const data = payload as Record<string, unknown>;
    const errorType = typeof data.error_type === "string" ? data.error_type : null;
    const summary = typeof data.error_summary === "string" ? data.error_summary : null;
    const traceId = typeof data.trace_id === "string" ? data.trace_id : null;
    const nextAction = typeof data.next_action === "string" ? data.next_action : null;
    const detail = data.detail;
    if (errorType || summary || nextAction) {
      const parts = [
        errorType ? `错误类型：${errorType}` : null,
        summary ? `原因：${summary}` : null,
        nextAction ? `下一步：${nextAction}` : null,
        traceId ? `trace_id：${traceId}` : null
      ].filter(Boolean);
      return new Error(parts.join("；"));
    }
    if (typeof detail === "string") {
      return new Error(`${method} ${path} failed: ${response.status} ${detail}`);
    }
    if (detail && typeof detail === "object") {
      return new Error(`${method} ${path} failed: ${response.status} ${JSON.stringify(detail)}`);
    }
  }

  return new Error(`${method} ${path} failed: ${response.status}`);
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include"
  });
  if (!response.ok) {
    handleUnauthorized(path, response.status);
    throw await buildApiError("GET", path, response);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    handleUnauthorized(path, response.status);
    throw await buildApiError("POST", path, response);
  }
  return response.json() as Promise<T>;
}

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "PUT",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    handleUnauthorized(path, response.status);
    throw await buildApiError("PUT", path, response);
  }
  return response.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "DELETE",
    credentials: "include"
  });
  if (!response.ok) {
    handleUnauthorized(path, response.status);
    throw await buildApiError("DELETE", path, response);
  }
  return response.json() as Promise<T>;
}

function handleUnauthorized(path: string, status: number) {
  if (status !== 401 || path.startsWith("/api/auth/") || typeof window === "undefined") {
    return;
  }
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.assign(`/login?next=${encodeURIComponent(current)}`);
}
