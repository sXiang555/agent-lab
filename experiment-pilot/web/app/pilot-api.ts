export type Evidence = { source_id: string; title: string; text: string };
export type Proposal = {
  proposal_id: string;
  review_id: string;
  baseline: string;
  candidate: string;
  baseline_revision: string;
  candidate_revision: string;
  split_fingerprint: string;
  training_protocol: string;
  evaluation_protocol: string;
  seed: number;
  metric_epoch?: number | null;
  state: "pending" | "approved" | "rejected";
  job_id: string | null;
  reason: string | null;
};
export type Review = {
  review_id: string;
  status: "pending_approval" | "running" | "complete";
  result: {
    status: string;
    summary: string;
    delta_ap_points: number | null;
    source_ids: string[];
    rerun_error?: string;
    note?: { text: string; sources: string[] };
  } | null;
  proposal: Proposal | null;
  evidence: Evidence[];
  usage: { model_calls: number; cost_usd: number | null; node_ms: number };
};
export type Showcase = Pick<Review, "result" | "evidence">;
export type Run = {
  run_id: string; label: string; ap: number | null; seed: number | null;
  split_fingerprint: string | null;
};
export type Health = {
  demo_auth: boolean; public_showcase: boolean; catalog: "demo" | "custom"; model: string; retrieval: string;
};
export type PilotEvent =
  | { type: "review"; data: { review_id: string } }
  | { type: "step"; data: { node: string } }
  | { type: "approval"; data: Proposal }
  | { type: "result"; data: Review }
  | { type: "error"; data: { code: number; message: string } };

async function request(path: string, token: string, init?: RequestInit) {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", "Bearer " + token);
  if (init?.body) headers.set("Content-Type", "application/json");
  const response = await fetch("/api/pilot" + path, { ...init, headers, cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(typeof payload?.detail === "string" ? payload.detail : `请求失败（${response.status}）`);
  }
  return response;
}

export async function readJson<T>(path: string, token = ""): Promise<T> {
  return (await request(path, token)).json();
}

export async function readStream(path: string, token: string, body: object,
                                 signal: AbortSignal, onEvent: (event: PilotEvent) => void) {
  const response = await request(path, token, { method: "POST", body: JSON.stringify(body), signal });
  if (!response.body) throw new Error("服务没有返回事件流");
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let hasResult = false;
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += value;
      for (;;) {
        const boundary = /\r?\n\r?\n/.exec(buffer);
        if (!boundary) break;
        const frame = buffer.slice(0, boundary.index);
        buffer = buffer.slice(boundary.index + boundary[0].length);
        const type = frame.split(/\r?\n/).find(line => line.startsWith("event: "))?.slice(7);
        const raw = frame.split(/\r?\n/).filter(line => line.startsWith("data: "))
          .map(line => line.slice(6)).join("\n");
        if (!type || !raw) continue;
        const event = { type, data: JSON.parse(raw) } as PilotEvent;
        if (event.type === "error") throw new Error(event.data.message);
        if (event.type === "result") hasResult = true;
        onEvent(event);
      }
    }
    if (!hasResult) throw new Error("事件流断开，可以重试本次请求");
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
