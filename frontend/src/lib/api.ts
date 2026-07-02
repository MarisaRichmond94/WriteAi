// Fetch + SSE helpers. All AI streams share the reference wire format:
//   {type:"chunk"|"citations"|"usage"|"error"|"done", ...}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json();
}

export interface SSEEvent {
  type: "chunk" | "citations" | "usage" | "error" | "done";
  content?: string;
  sources?: unknown[];
  message?: string;
  cost_usd?: number;
  [k: string]: unknown;
}

export async function* streamSSE(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<SSEEvent> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    throw new Error(`stream failed: ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const raw of events) {
      const line = raw.trim();
      if (!line.startsWith("data:")) continue;
      try {
        yield JSON.parse(line.slice(5)) as SSEEvent;
      } catch {
        /* partial frame — ignore */
      }
    }
  }
}
