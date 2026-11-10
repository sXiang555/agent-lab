from dataclasses import dataclass


@dataclass(frozen=True)
class Case:
    name: str
    topic: str
    queries: tuple[str, ...]
    status: str
    source: str | None = None
    reason: str | None = None
    delta: float | None = None
    rerun: bool = False
    pending: bool = False


def pairs(left: str, right: str) -> tuple[str, ...]:
    return (
        f"比较 {left} 和 {right} 的 AP。",
        f"{left} 对 {right}，两组实验能做公平对照吗？",
        f"以 {left} 为基线，核对 {right} 的跑分变化。",
        f"请复盘 baseline {left} 与 candidate {right}。",
        f"{left} vs {right}，报告可以支持怎样的 AP 结论？",
    )


CASES = (
    Case("improvement", "compare", pairs("DET-001", "DET-002"), "comparable", "run:DET-002", delta=1.2),
    Case("reverse", "compare", pairs("DET-002", "DET-001"), "comparable", "run:DET-002", delta=-1.2),
    Case("split", "compare", pairs("DET-001", "DET-003"), "incomparable", "run:DET-003", "split_fingerprint"),
    Case("no-metrics", "compare", pairs("DET-001", "DET-004"), "insufficient_evidence", "run:DET-004", "missing_ap"),
    Case("seed", "compare", pairs("DET-001", "DET-005"), "incomparable", "run:DET-005", "seed"),
    Case("budget", "compare", pairs("DET-001", "DET-006"), "incomparable", "run:DET-006", "training_protocol"),
    Case("regression", "compare", pairs("DET-001", "DET-007"), "comparable", "run:DET-007", delta=-1.0),
    Case("evaluation", "compare", pairs("DET-001", "DET-008"), "incomparable", "run:DET-008", "evaluation_protocol"),
    Case("same-run", "compare", pairs("DET-001", "DET-001"), "incomparable", "run:DET-001", "same_run"),
    Case("unknown-pair", "compare", pairs("DET-001", "DET-999"), "insufficient_evidence", reason="missing_pair"),
    Case("lookup", "lookup", ("查 DET-001", "DET-001 的主 AP 呢？", "显示 DET-001 的评估记录",
                              "DET-001 的 seed 是什么？", "读取实验 DET-001"),
         "lookup", "run:DET-001"),
    Case("lookup-incomplete", "lookup", ("查 DET-004", "看 DET-004 的 AP", "读一下 DET-004",
                                         "DET-004 有评估结果吗？", "展示 DET-004 的运行记录"),
         "lookup", "run:DET-004"),
    Case("lookup-private", "scope", ("查 VIS-001", "VIS-001 的 AP 呢？", "给我 VIS-001 记录",
                                      "我想看 VIS-001 的 seed", "展示 VIS-001"),
         "insufficient_evidence", reason="run_unavailable"),
    Case("guide-seed", "guide", ("如何用随机种子做成对复现？", "实验的随机种子和复现怎么控制？",
                                 "如何用多个 seed 衡量波动？", "复现时如何选择随机种子？",
                                 "怎么做随机种子的配对实验？"), "guide", "kb:seeds"),
    Case("guide-ap", "guide", ("AP 指标与评估口径是什么？", "COCO AP 指标评估口径怎么记录？",
                               "怎么理解 AP 指标与 AP50？", "如何核对 AP 指标的评估口径？",
                               "主 AP 指标与评估口径在手册哪一条？"), "guide", "kb:ap"),
    Case("guide-latency", "guide", ("如何测延迟与吞吐？", "延迟和吞吐测试怎么控制？",
                                    "怎么测延迟的 P95？", "延迟与吞吐报告写什么？",
                                    "测延迟时 warmup 要固定吗？"), "guide", "kb:latency"),
    Case("guide-oom", "guide", ("怎么定位显存不足？", "训练时显存不足怎么定位？",
                                "定位显存不足先看什么？", "显存不足时检查什么？",
                                "显存不足的定位步骤是什么？"), "guide", "kb:oom"),
    Case("pending-rerun", "approval", pairs("DET-001", "DET-003"), "incomparable", "run:DET-003",
         "split_fingerprint", rerun=True, pending=True),
    Case("denied-rerun", "approval", pairs("DET-001", "VIS-001"), "insufficient_evidence",
         reason="missing_pair", rerun=True),
    Case("unsupported", "unsupported", ("今天吃什么？", "帮我订票", "这周天气如何？",
                                         "讲个笑话", "帮我写一首诗"), "unsupported"),
)
