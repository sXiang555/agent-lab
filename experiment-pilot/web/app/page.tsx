"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import {
  readJson, readStream, type Health, type PilotEvent, type Proposal, type Review, type Run, type Showcase,
} from "./pilot-api";

const samples = [
  { id: "01", title: "验证 AP 提升", question: "对比 DET-001 和 DET-002，AP 提升了多少？", rerun: false },
  { id: "02", title: "发现数据划分变化", question: "DET-001 和 DET-003 能公平比较吗？", rerun: false },
  { id: "03", title: "申请按基线口径补跑", question: "比较 DET-001 和 DET-003，并申请补跑候选实验。", rerun: true },
  { id: "04", title: "查看多 seed 复现方法", question: "如何用随机种子做成对复现？", rerun: false },
];
const publicSamples = [
  { id: "improvement", title: "核对 AP 提升" },
  { id: "split", title: "识别数据划分差异" },
  { id: "missing", title: "识别缺失评估证据" },
] as const;
const nodes: Record<string, string> = {
  triage: "识别实验与任务", collect: "查询记录与手册", draft: "计算并整理结论",
  verify: "核对引用", propose: "创建待审批申请", approval: "保存审批结果",
};
const statuses: Record<string, string> = {
  comparable: "口径一致", incomparable: "口径不一致", insufficient_evidence: "证据不足",
  lookup: "实验记录", guide: "手册解答", unsupported: "需补充问题",
};
type Task = { path: string; token: string; body: object };

export default function Workbench() {
  const [health, setHealth] = useState<Health | null>(null);
  const [showcase, setShowcase] = useState<Showcase | null>(null);
  const [view, setView] = useState<"review" | "desk">("review");
  const [analyst, setAnalyst] = useState("");
  const [reviewer, setReviewer] = useState("");
  const [question, setQuestion] = useState("");
  const [rerun, setRerun] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]);
  const [reviewId, setReviewId] = useState("");
  const [review, setReview] = useState<Review | null>(null);
  const [trace, setTrace] = useState<string[]>([]);
  const [approvals, setApprovals] = useState<Proposal[]>([]);
  const [selected, setSelected] = useState<Proposal | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const controller = useRef<AbortController | null>(null);
  const retry = useRef<Task | null>(null);

  useEffect(() => {
    let active = true;
    const savedId = sessionStorage.getItem("pilot-review-id") ?? "";
    if (/^[a-f0-9]{32}$/.test(savedId)) setReviewId(savedId);
    readJson<Health>("/health").then(info => {
      if (!active) return;
      setHealth(info);
      if (info.catalog === "demo" && info.demo_auth) setQuestion(previous => previous || samples[0].question);
      if (info.demo_auth) {
        setAnalyst("demo-analyst");
        setReviewer("demo-reviewer");
        if (/^[a-f0-9]{32}$/.test(savedId)) {
          void readJson<Review>(`/reviews/${savedId}`, "demo-analyst").then(restored => {
            if (active && sessionStorage.getItem("pilot-review-id") === savedId) setReview(restored);
          }).catch(() => {
            if (active && sessionStorage.getItem("pilot-review-id") === savedId) {
              sessionStorage.removeItem("pilot-review-id");
              setReviewId("");
            }
          });
        }
      }
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; controller.current?.abort(); };
  }, []);

  async function listRuns(token = analyst) {
    if (!token) return;
    try { setRuns(await readJson<Run[]>("/runs", token)); }
    catch (err) { setError((err as Error).message); }
  }

  useEffect(() => {
    if (!health?.demo_auth) return;
    let active = true;
    readJson<Run[]>("/runs", "demo-analyst").then(rows => {
      if (active) setRuns(rows);
    }).catch((err: Error) => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [health]);

  async function refreshDesk(token = reviewer) {
    if (!token) return;
    try { setApprovals(await readJson<Proposal[]>("/approvals", token)); }
    catch (err) { setError((err as Error).message); }
  }

  async function stream(task: Task) {
    if (controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setNotice("");
    setTrace([]);
    retry.current = task;
    const isDecision = task.path.endsWith("/approval");
    let final: Review | null = null;
    function event(item: PilotEvent) {
      if (item.type === "review" && !isDecision) {
        setReviewId(item.data.review_id);
        sessionStorage.setItem("pilot-review-id", item.data.review_id);
      }
      if (item.type === "step") setTrace(previous => [...previous, item.data.node]);
      if (item.type === "result") {
        final = item.data;
        if (!isDecision || reviewId === item.data.review_id) setReview(item.data);
      }
    }
    try {
      await readStream(task.path, task.token, task.body, abort.signal, event);
      retry.current = null;
      const completed = final as Review | null;
      if (isDecision && completed?.proposal) {
        setNotice(completed.proposal.job_id ? "已通过，补跑任务已进入演示队列。" : "已驳回申请。");
        setSelected(null);
        setReason("");
        await refreshDesk();
      }
      return completed;
    } catch (err) {
      setError(abort.signal.aborted ? "已停止接收。可以重试同一请求。" : (err as Error).message);
    } finally {
      controller.current = null;
      setBusy(false);
    }
    return null;
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || !analyst || busy) return;
    const body = { request_id: crypto.randomUUID(), question, request_rerun: rerun };
    const path = reviewId ? `/reviews/${reviewId}/turns` : "/reviews";
    const result = await stream({ path, token: analyst, body });
    if (result) {
      setQuestion("");
      setRerun(false);
    }
  }

  async function readReview() {
    if (!reviewId || !analyst) return;
    try { setReview(await readJson<Review>(`/reviews/${reviewId}`, analyst)); }
    catch (err) { setError((err as Error).message); }
  }

  async function decide(approve: boolean) {
    if (!selected || !reason.trim()) return;
    const current = selected;
    await stream({
      path: `/reviews/${current.review_id}/approval`,
      token: reviewer,
      body: { proposal_id: current.proposal_id, approve, reason: reason.trim() },
    });
  }

  async function loadExample(id: typeof publicSamples[number]["id"]) {
    setError("");
    try {
      setShowcase(await readJson<Showcase>("/showcase/" + id));
    } catch (err) {
      setError((err as Error).message);
    }
  }

  function switchView(next: "review" | "desk") {
    setView(next);
    setError("");
    setNotice("");
    if (next === "desk") void refreshDesk();
  }

  function reset() {
    sessionStorage.removeItem("pilot-review-id");
    setReview(null);
    setReviewId("");
    setTrace([]);
    setError("");
    setQuestion(health?.catalog === "demo" ? samples[0].question : "");
    setRerun(false);
    retry.current = null;
  }

  const citations = new Set([...(review?.result?.source_ids ?? []),
                             ...(review?.result?.note?.sources ?? [])]);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">EP</span><span>ExperimentPilot<small>目标检测实验工作台</small></span></div>
        <div className="mode"><span className={health ? "light" : "light offline"} />
          {health ? `${health.demo_auth ? "演示" : "受限"} · ${health.model === "rules" ? "规则模式" : "模型模式"}` : "连接服务"}
        </div>
      </header>

      <main>
        <div className="intro">
          <div className="eyebrow">RT-DETR EXPERIMENT REVIEW</div>
          <h1>用证据复盘每一次实验。</h1>
          <p>核对 baseline、追踪 AP 变化，把需要复现的结果交给审批队列。</p>
        </div>

        <nav className="tabs" aria-label="工作台视图">
          <button className={view === "review" ? "current" : ""} aria-pressed={view === "review"}
            disabled={busy} onClick={() => switchView("review")}>实验复盘</button>
          <button className={view === "desk" ? "current" : ""} aria-pressed={view === "desk"}
            disabled={busy} onClick={() => switchView("desk")}>审批工作台</button>
        </nav>

        {error && <div className="alert" role="alert">
          <span>{error}</span>{retry.current && !busy &&
            <button className="link" onClick={() => { if (retry.current) void stream(retry.current); }}>重试同一请求</button>}
        </div>}
        {notice && <div className="notice" role="status">{notice}</div>}

        {view === "review" && health?.public_showcase && !health.demo_auth &&
          <section className="panel public-sample">
            <div className="panel-head">
              <div><div className="eyebrow">PUBLIC / EXAMPLE</div><h2>公开样例</h2></div>
              <span className="tag">演示数据</span>
            </div>
            <p className="micro">无需令牌即可查看 AP 计算、口径差异和原始记录。完整工作流在下方工作台。</p>
            <div className="examples">
              {publicSamples.map(sample =>
                <button key={sample.id} type="button" onClick={() => loadExample(sample.id)}>
                  {sample.title}
                </button>)}
            </div>
            {showcase?.result && <div aria-live="polite" className="result">
              <span className="tag">{statuses[showcase.result.status]}</span>
              <p>{showcase.result.summary}</p>
              {showcase.evidence.map(item => <details key={item.source_id}>
                <summary><span>{item.title}</span></summary>
                <code>{item.source_id}</code><p>{item.text}</p>
              </details>)}
            </div>}
          </section>}

        {view === "review" ? (
          <div className="workspace">
            <section className="panel primary">
              <div className="panel-head">
                <div><div className="eyebrow">01 / REVIEW</div><h2>实验复盘</h2></div>
                <button className="ghost" disabled={busy} onClick={reset}>新建复盘</button>
              </div>
              {health && !health.demo_auth && <label className="field">实验员令牌
                <input type="password" value={analyst} onChange={e => setAnalyst(e.target.value)} autoComplete="off" />
                <div className="form-actions">
                  <button type="button" className="link" onClick={() => listRuns()}>读取实验目录</button>
                  {reviewId && <button type="button" className="link" onClick={readReview}>恢复复盘</button>}
                </div>
              </label>}
              {health?.catalog === "demo" && (health.demo_auth || analyst) && <div className="examples">
                {samples.map(s => <button key={s.id} type="button" disabled={busy}
                  onClick={() => { setQuestion(s.question); setRerun(s.rerun); }}>
                  <span>{s.id}</span>{s.title}
                </button>)}
              </div>}
              <form onSubmit={submit}>
                <label className="field">实验问题
                  <textarea value={question} onChange={e => setQuestion(e.target.value)} maxLength={2000}
                    placeholder="输入问题，或追问刚才这组实验…" rows={3} required />
                </label>
                <div className="form-actions">
                  <label className="checkbox"><input type="checkbox" checked={rerun}
                    onChange={e => setRerun(e.target.checked)} /> 提交补跑申请</label>
                  {busy ? <button className="ghost" type="button" onClick={() => controller.current?.abort()}>停止接收</button> :
                    <button className="accent" type="submit" disabled={!analyst || !question.trim() || review?.status === "pending_approval"}>
                      {reviewId ? "提交追问" : "开始复盘"} <span aria-hidden="true">↗</span>
                    </button>}
                </div>
              </form>

              {(trace.length > 0 || busy) && <div className="timeline" aria-live="polite">
                {trace.map((node, index) => <span key={node + index}>✓ {nodes[node] ?? node}</span>)}
                {busy && <span className="working">处理中…</span>}
              </div>}

              {review?.result && <div className="result" aria-live="polite">
                <div className="result-top"><span className="tag">{statuses[review.result.status] ?? review.result.status}</span>
                  <span className="micro">节点耗时 {Math.round(review.usage.node_ms)} ms · 模型调用 {review.usage.model_calls}</span></div>
                {review.result.delta_ap_points !== null && <div className="delta">
                  {review.result.delta_ap_points > 0 ? "+" : ""}{review.result.delta_ap_points}<small> AP 点</small>
                </div>}
                <p>{review.result.summary}</p>
                {review.result.note && <p className="note">{review.result.note.text}</p>}
                {review.result.rerun_error && <p className="warning">{review.result.rerun_error}</p>}
                {review.proposal && <div className="proposal-strip">
                  <span>{review.proposal.state === "pending" ? "待人工审批" :
                    review.proposal.state === "approved" ? "已批准 · 已进入演示队列" : "已驳回"}
                    {review.proposal.reason && ` · ${review.proposal.reason}`}</span>
                  {review.proposal.state === "pending" && <button className="link" onClick={readReview}>刷新审批状态</button>}
                </div>}
              </div>}
            </section>

            <aside className="panel side">
              <div className="panel-head"><div><div className="eyebrow">02 / EVIDENCE</div><h2>证据与记录</h2></div></div>
              {review?.evidence.length ? <div className="sources">
                {review.evidence.map(item => <details key={item.source_id} open={citations.has(item.source_id)}>
                  <summary><span>{item.title}</span>{citations.has(item.source_id) && <span className="tag">已引用</span>}</summary>
                  <code>{item.source_id}</code><p>{item.text}</p>
                </details>)}
              </div> : <div className="empty">运行复盘后，实验记录和手册引用会显示在这里。</div>}
              <h3>实验目录</h3>
              <div className="runs">
                {runs.map(run => <div key={run.run_id}>
                  <span>
                    {health?.catalog === "custom" ?
                      <button type="button" className="link" disabled={busy}
                        aria-label={"将 " + run.run_id + " 加入问题"}
                        onClick={() => setQuestion(text => [text.trim(), run.run_id].filter(Boolean).join(" "))}>
                        <code>{run.run_id}</code>
                      </button> : <code>{run.run_id}</code>}
                    <small>{run.label}</small>
                  </span>
                  <strong>{run.ap === null ? "—" : (run.ap * 100).toFixed(2)}</strong>
                </div>)}
                {!runs.length && <div className="empty">目录暂无记录</div>}
              </div>
            </aside>
          </div>
        ) : (
          <div className="workspace">
            <section className="panel primary">
              <div className="panel-head"><div><div className="eyebrow">01 / QUEUE</div><h2>待审批申请</h2></div>
                <button className="ghost" onClick={() => refreshDesk()} disabled={busy}>刷新队列</button></div>
              {health && !health.demo_auth && <label className="field">审批员令牌
                <input type="password" value={reviewer} onChange={e => setReviewer(e.target.value)} autoComplete="off" />
              </label>}
              {!approvals.length && <div className="empty">暂无待审批申请。可以先在实验复盘页申请一次补跑。</div>}
              {approvals.map(p => <button className="queue-item" key={p.proposal_id} type="button"
                disabled={busy} onClick={() => { setSelected(p); setReason(""); }}>
                <span><strong>{p.baseline} → {p.candidate}</strong><small>{p.split_fingerprint} · seed {p.seed}</small></span>
                <span className="tag">待审批 ↗</span>
              </button>)}
            </section>
            <section className="panel side">
              <div className="panel-head"><div><div className="eyebrow">02 / DECISION</div><h2>审批详情</h2></div></div>
              {selected ? <>
                <dl className="details">
                  <dt>基线 / 候选</dt><dd>{selected.baseline} / {selected.candidate}</dd>
                  <dt>代码版本</dt><dd>{selected.baseline_revision} / {selected.candidate_revision}</dd>
                  <dt>数据划分</dt><dd>{selected.split_fingerprint}</dd>
                  <dt>训练口径</dt><dd>{selected.training_protocol}</dd>
                  <dt>评估口径</dt><dd>{selected.evaluation_protocol}</dd>
                  <dt>随机种子</dt><dd>{selected.seed}</dd>
                  {selected.metric_epoch != null && <><dt>取分 epoch</dt><dd>{selected.metric_epoch}</dd></>}
                </dl>
                <label className="field">审批理由
                  <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} maxLength={300} />
                </label>
                <div className="decision-actions">
                  <button className="ghost" disabled={busy || !reason.trim()} onClick={() => decide(false)}>驳回</button>
                  <button className="accent" disabled={busy || !reason.trim()} onClick={() => decide(true)}>批准并排队</button>
                </div>
              </> : <div className="empty">选择一条申请，核对补跑口径后作出决策。</div>}
            </section>
          </div>
        )}
        <footer><span>ExperimentPilot</span><span>RT-DETR / RT-DETRv2 实验复盘</span></footer>
      </main>
    </div>
  );
}
