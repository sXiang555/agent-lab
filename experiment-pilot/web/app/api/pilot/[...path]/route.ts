import type { NextRequest } from "next/server";

type Context = { params: Promise<{ path: string[] }> };

async function proxy(request: NextRequest, context: Context) {
  const { path } = await context.params;
  const joined = path.join("/");
  const allowed = request.method === "GET"
    ? /^(?:health|ready|runs|approvals|showcase\/(?:improvement|split|missing)|reviews\/[a-f0-9]{32})$/
    : /^(?:reviews|reviews\/[a-f0-9]{32}\/(?:turns|approval))$/;
  if (!allowed.test(joined)) return Response.json({ detail: "接口不存在" }, { status: 404 });
  const base = process.env.PILOT_API_URL || "http://127.0.0.1:8000";
  const target = new URL("/" + path.map(encodeURIComponent).join("/"), base);
  const headers = new Headers();
  for (const name of ["authorization", "content-type"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  let body: ArrayBuffer | undefined;
  if (request.method === "POST" && request.body) {
    const reader = request.body.getReader();
    const buffer = new Uint8Array(16_384);
    let length = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (length + value.length > buffer.length) {
        await reader.cancel();
        return Response.json({ detail: "请求体过大" }, { status: 413 });
      }
      buffer.set(value, length);
      length += value.length;
    }
    body = buffer.buffer.slice(0, length);
  }
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      redirect: "error",
      signal: request.signal,
    });
    const resultHeaders = new Headers({ "Cache-Control": "no-store" });
    for (const name of ["content-type", "x-accel-buffering", "retry-after"]) {
      const value = upstream.headers.get(name);
      if (value) resultHeaders.set(name, value);
    }
    return new Response(upstream.body, { status: upstream.status, headers: resultHeaders });
  } catch {
    return Response.json({ detail: "工作流服务暂时不可用" }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST };
