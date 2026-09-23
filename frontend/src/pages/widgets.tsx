const toneClass: Record<string, string> = {
  ok: "pill-ok",
  err: "pill-err",
  warn: "pill-warn",
  run: "pill-warn",
  mute: "pill-mute",
  x: "pill-mute",
  L1: "pill-ok",
  L2: "pill-warn",
  L3: "pill-err",
  C: "pill-mute",
};

export function StatusBadge({
  tone,
  text,
  status,
}: {
  tone?: string;
  text?: string;
  status?: { level: string; mr_url: string } | null;
}) {
  if (status === undefined)
    return <span className={`pill ${tone ? toneClass[tone] ?? "pill-mute" : "pill-mute"}`}>{text ?? ""}</span>;
  if (!status) return <span className="pill pill-mute">待处理</span>;
  if (status.mr_url)
    return (
      <span className="pill-row">
        <span className="pill pill-ok">已开请求</span>
        <a className="pill-link" href={status.mr_url} target="_blank" rel="noreferrer">
          查看请求
        </a>
      </span>
    );
  const label =
    status.level === "L1"
      ? "已验证"
      : status.level === "L2"
        ? "待人工看"
        : status.level === "L3"
          ? "修不好"
          : status.level || "已跑过";
  const hint =
    status.level === "L1"
      ? "重扫和测试都过了，可以合"
      : status.level === "L2"
        ? "只有建议片段，需要人动手"
        : status.level === "L3"
          ? "自动修没通过，点行看原因"
          : "";
  return (
    <span className={`pill ${toneClass[status.level] ?? "pill-mute"}`} title={hint}>
      {label}
    </span>
  );
}
