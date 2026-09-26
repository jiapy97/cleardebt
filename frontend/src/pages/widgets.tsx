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
  skip: "pill-mute",
};

// Triage tiers from cleardebt/triage.py; letter codes come from records written before the rename.
export const REPAIR_TIERS = ["dependency", "rewrite", "llm"];
const LEGACY_TIERS: Record<string, string> = { A: "dependency", B: "llm", C: "skip", unknown: "unsupported" };
export const normalizeTier = (tier?: string) => LEGACY_TIERS[tier ?? ""] ?? tier ?? "";
export const TIER_LABELS: Record<string, string> = {
  dependency: "依赖升级",
  rewrite: "规则改写",
  llm: "AI 修复",
  skip: "不修",
  unsupported: "语言未接入",
};
export const FIX_METHOD_LABELS: Record<string, string> = { sca: "依赖升级", mechanical: "规则改写", llm: "AI 修复" };
const LEVEL_LABELS: Record<string, string> = { L1: "修好了", L2: "要人工改", L3: "没修成", skip: "不修", C: "不修" };
export const levelLabel = (level?: string) => LEVEL_LABELS[level ?? ""] ?? level ?? "";

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
  const label = levelLabel(status.level) || "已跑过";
  const hint =
    status.level === "L1"
      ? "告警消失了，测试也过了，可以合并"
      : status.level === "L2"
        ? "只给了修改建议，需要人来改"
        : status.level === "L3"
          ? "这次改动没通过检查，点开这一行看原因"
          : status.level === "skip" || status.level === "C"
            ? "不在可修范围，Agent 没有动这条"
            : "";
  return (
    <span className={`pill ${toneClass[status.level] ?? "pill-mute"}`} title={hint}>
      {label}
    </span>
  );
}
