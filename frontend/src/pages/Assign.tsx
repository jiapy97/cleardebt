import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Select, Space, Spin, Table, Tag, Tooltip, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api, issueId, issueSelection, type AssignDecision, type Issue } from "../lib/api";
import { useRepoChoices } from "../lib/useOverview";
import { REPAIR_TIERS, StatusBadge, TIER_LABELS, normalizeTier } from "./widgets";

export default function AssignPage() {
  const { choices, def, overview } = useRepoChoices();
  const [repo, setRepo] = useState("");
  const [cache, setCache] = useState<Record<string, { issues: Issue[]; note: string }>>({});
  const [picked, setPicked] = useState<string[]>([]);
  const cur = repo || def;
  const readOnly = overview?.bindings.some((binding) => binding.sonar_key === cur && binding.read_only === true) ?? false;
  const shown = (cur && cache[cur]) || null;
  const [phase, setPhase] = useState("");
  const [scanning, setScanning] = useState(false);
  const [scanError, setScanError] = useState("");
  const [assigning, setAssigning] = useState(false);
  const [assignSession, setAssignSession] = useState<number | null>(null);
  const [assignResult, setAssignResult] = useState<{
    opened: number;
    total: number;
    failed: AssignDecision[];
    warning?: string;
  } | null>(null);
  const [assignError, setAssignError] = useState("");
  const [showHidden, setShowHidden] = useState(false);

  const visible = (shown?.issues ?? []).filter((r) => showHidden || !r.suppressed);
  const hiddenCount = (shown?.issues ?? []).filter((r) => r.suppressed).length;

  const toggleSuppress = (r: Issue, off: boolean) => {
    (off ? api.unsuppress(cur, r.rule, r.path, r.line ?? 0) : api.suppress(cur, r.rule, r.path, r.line ?? 0))
      .then(() => load.mutate(cur))
      .catch((e: Error) => message.error(e.message));
  };

  const list = useMutation({
    mutationFn: (target?: string) => api.listIssues(target ?? cur),
    onSuccess: () => {
      setPicked([]);
    },
    onError: (e: Error) => message.error(e.message),
  });

  useEffect(() => {
    if (!scanning || !cur) return;
    setPhase("正在准备重扫…");
    const timer = setInterval(() => {
      api
        .scanProgress(cur)
        .then((p) => {
          if (p.step === "DONE") {
            setScanning(false);
            load.mutate(cur);
          } else if (p.step.startsWith("失败：")) {
            setScanning(false);
            setScanError(`重扫${p.step}`);
            load.mutate(cur);
          } else if (p.step && !p.stale) {
            setPhase(p.step);
          }
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scanning, cur]);

  const load = useMutation({
    mutationFn: (target: string) => api.issueSnapshot(target),
    onSuccess: (d, target) => {
      setCache((c) => ({ ...c, [target]: { issues: d.issues, note: d.scan_note } }));
      if (target === cur) setPicked([]);
    },
    onError: () => {},
  });

  useEffect(() => {
    if (!cur || cache[cur] || load.isPending) return;
    load.mutate(cur);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur, Object.keys(cache).join(",")]);

  const assign = useMutation({
    mutationFn: () => {
      const selected = (shown?.issues ?? []).filter((row) => picked.includes(issueId(row)));
      return api.assign(cur, selected.map(issueSelection));
    },
    onSuccess: (d) => {
      if (d.already_running) {
        message.info("这个项目已经在跑了，等它跑完。");
        setAssigning(false);
        return;
      }
      setAssignSession(d.session_id ?? null);
    },
    onError: (e: Error) => {
      setAssigning(false);
      setAssignError(e.message);
    },
  });

  useEffect(() => {
    if (!assigning || assignSession == null || !cur) return;
    const timer = setInterval(() => {
      api
        .sessionDetail(assignSession)
        .then((s) => {
          const details = (s.details ?? {}) as {
            decisions?: AssignDecision[];
            error?: string;
            warning?: string;
          };
          if (s.status === "completed") {
            setAssigning(false);
            const decisions = details.decisions ?? [];
            const opened = decisions.filter((x) => x.action === "opened" || x.action === "already").length;
            const failed = decisions.filter((x) => x.level === "L3" || x.action === "no_mr");
            setAssignResult({ opened, total: decisions.length, failed, warning: details.warning });
            if (!failed.length) {
              message.success(`已指派 ${decisions.length} 条，开请求 ${opened}，列表已刷新`);
            }
            setPicked([]);
            load.mutate(cur);
          } else if (s.status === "failed") {
            setAssigning(false);
            setAssignError(details.error ? `指派失败：${details.error}` : "指派失败，后台已记录。");
          }
        })
        .catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assigning, assignSession, cur]);

  const columns: ColumnsType<Issue> = [
    {
      title: "规则",
      dataIndex: "rule",
      key: "rule",
      width: 180,
      ellipsis: true,
      render: (v: string) => <strong>{v}</strong>,
    },
    { title: "文件", dataIndex: "path", key: "path", width: 160, ellipsis: true },
    {
      title: "行",
      dataIndex: "line",
      key: "line",
      width: 70,
      render: (v: number) => (v ? `L${v}` : "—"),
    },
    {
      title: "说明",
      dataIndex: "message",
      key: "message",
      width: 280,
      ellipsis: { showTitle: false },
      render: (v: string, r) => (
        <Tooltip
          placement="topLeft"
          title={r.message_zh && r.message_zh !== v ? <>{r.message_zh}<br />{v}</> : v}
        >
          <span>
            {r.is_new && !r.suppressed && (
              <span className="pill pill-warn" style={{ marginRight: 6 }}>
                新
              </span>
            )}
            {r.suppressed && (
              <span className="pill pill-mute" style={{ marginRight: 6 }}>
                已忽略
              </span>
            )}
            {r.message_zh || v}
          </span>
        </Tooltip>
      ),
    },
    {
      title: "是否可以指派给 Agent",
      key: "eligible",
      width: 170,
      render: (_, r) => <StatusBadge tone={!readOnly && r.eligible ? "ok" : "mute"} text={!readOnly && r.eligible ? "是" : "否"} />,
    },
    {
      title: "结论",
      key: "tier",
      width: 130,
      render: (_, r) => {
        if (r.tier_source === "sonar_quick_fix") {
          return <Tooltip title={r.eligible ? "Sonar 本次扫描标记这条告警有 Quick Fix" : "Sonar 本次扫描未标记这条告警有 Quick Fix"}>
            <Tag color={r.eligible ? "green" : "orange"}>{r.eligible ? "Sonar Quick Fix" : "无 Quick Fix"}</Tag>
          </Tooltip>;
        }
        if (r.tier_source === "sonar_ai_codefix_list") {
          const tier = normalizeTier(r.tier);
          const listed = REPAIR_TIERS.includes(tier);
          const hint = tier === "rewrite"
            ? "在可修规则清单内：先用确定性规则改写，不行再交给 AI"
            : listed
              ? "在可修规则清单内，交给 AI 修复"
              : tier === "unsupported" ? "这门语言 Agent 还没接入" : "不在可修规则清单内";
          return <Tooltip title={hint}>
            <Tag color={listed ? "green" : tier === "unsupported" ? undefined : "orange"}>{TIER_LABELS[tier] ?? tier}</Tag>
          </Tooltip>;
        }
        return <Tooltip title="依赖升级由独立的 SCA 流程处理"><Tag color="green">依赖升级</Tag></Tooltip>;
      },
    },
    {
      title: "最新状态",
      key: "status",
      width: 170,
      render: (_, r) => <StatusBadge status={r.status} />,
    },
    {
      title: "操作",
      key: "op",
      width: 90,
      render: (_, r) =>
        r.suppressed ? (
          <a onClick={() => toggleSuppress(r, true)}>取消忽略</a>
        ) : (
          <a onClick={() => toggleSuppress(r, false)}>忽略</a>
        ),
    },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card>
        <Space wrap>
          <Select
            style={{ width: 220 }}
            placeholder="先在接入配置里选仓库"
            value={cur || undefined}
            onChange={(v) => {
              setRepo(v);
              setPicked([]);
              setScanning(false);
              setPhase("");
              setScanError("");
              setAssigning(false);
              setAssignSession(null);
              setAssignResult(null);
              setAssignError("");
            }}
            options={choices.map((c) => ({ label: c.key, value: c.key }))}
          />
          <Button
            type="primary"
            loading={scanning}
            disabled={!cur}
            onClick={() => {
              setScanning(true);
              setScanError("");
              setPhase("正在准备重扫…");
              list.mutate(cur);
            }}
          >
            {scanning ? "正在重扫入库…" : shown ? "重新扫描" : "列出告警"}
          </Button>
          {scanning && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#595959" }}>
              <Spin size="small" /> {phase || "正在准备重扫…"}
            </span>
          )}
        </Space>
        {load.isPending && !shown && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon message="正在读库里快照…" />
        )}
        {scanError && (
          <Alert
            style={{ marginTop: 12 }}
            type="error"
            showIcon
            message={scanError}
            closable
            onClose={() => setScanError("")}
          />
        )}
        {shown?.note && <Alert style={{ marginTop: 12 }} type="success" showIcon message={shown.note} />}
        {readOnly && <Alert style={{ marginTop: 12 }} type="info" showIcon message="这个公开仓库没有托管平台令牌：可以拉取、扫描和查看问题，不能指派修复。" />}
      </Card>
      <Card title={`告警列表（${visible.length} 条${hiddenCount > 0 ? `，已忽略 ${hiddenCount} 条` : ""}）`}>
        {hiddenCount > 0 && (
          <div style={{ marginBottom: 8 }}>
            <Checkbox checked={showHidden} onChange={(e) => setShowHidden(e.target.checked)}>
              显示已忽略（{hiddenCount}）
            </Checkbox>
          </div>
        )}
        <Table<Issue>
          rowKey={issueId}
          columns={readOnly
            ? columns.filter((column) => !["eligible", "tier", "status", "op"].includes(String(column.key)))
            : columns}
          dataSource={visible}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          rowSelection={readOnly ? undefined : {
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys as string[]),
            getCheckboxProps: (r) => ({ disabled: !r.eligible }),
          }}
          locale={{ emptyText: cur ? "库里还没有这个项目的快照，点「重新扫描」扫一遍入库" : "选好项目后点「重新扫描」" }}
        />
        {!readOnly && (
          <Button
            type="primary"
            loading={assigning}
            disabled={picked.length === 0}
            onClick={() => {
              setAssigning(true);
              setAssignSession(null);
              setAssignResult(null);
              setAssignError("");
              assign.mutate();
            }}
          >
            指派给 Agent{picked.length > 0 ? `（${picked.length}）` : ""}
          </Button>
        )}
        {assigning && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, marginLeft: 12, color: "#595959" }}>
            <Spin size="small" /> 正在跑，第 {assignSession ?? ""} 会话…
          </span>
        )}
        {assignError && (
          <Alert
            style={{ marginTop: 12 }}
            type="error"
            showIcon
            message={assignError}
            closable
            onClose={() => setAssignError("")}
          />
        )}
        {assignResult && assignResult.failed.length > 0 && (
          <Alert
            style={{ marginTop: 12 }}
            type="warning"
            showIcon
            message={`跑完 ${assignResult.total} 条，开请求 ${assignResult.opened}，${assignResult.failed.length} 条没开成`}
            description={
              <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
                {assignResult.failed.map((f, i) => (
                  <li key={i}>
                    {f.rule} {f.path}：{f.reason || "没开成"}
                  </li>
                ))}
              </ul>
            }
            closable
            onClose={() => setAssignResult(null)}
          />
        )}
        {assignResult && assignResult.failed.length === 0 && assignResult.total > 0 && (
          <Alert
            style={{ marginTop: 12 }}
            type="success"
            showIcon
            message={`跑完 ${assignResult.total} 条，开请求 ${assignResult.opened}`}
            closable
            onClose={() => setAssignResult(null)}
          />
        )}
      </Card>
    </Space>
  );
}
