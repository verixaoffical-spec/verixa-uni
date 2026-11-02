export interface Reply {
  status: number;        // 0 when the server could not be reached
  timeout?: boolean;
  retryAfter: number;    // seconds, from the Retry-After header
  detail?: any;          // FastAPI's error detail: a string, { field, message } for a form field, or { retry_after }
  data?: any;            // the whole answer, for successful replies
}

// Posts the form as JSON. Gives up after 15 seconds so the button never spins forever.
export async function send(path: string, payload: object): Promise<Reply> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(path, {
      method: 'POST',
      credentials: 'same-origin',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    return { status: res.status, detail: data.detail, data, retryAfter: Number(res.headers.get('Retry-After')) || 0 };
  } catch (err) {
    return { status: 0, timeout: (err as Error).name === 'AbortError', retryAfter: 0 };
  } finally {
    clearTimeout(timer);
  }
}
