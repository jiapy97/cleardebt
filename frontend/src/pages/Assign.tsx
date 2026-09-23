import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Select, Space, Spin, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api, type Issue } from "../lib/api";
import { useRepoChoices } from "../lib/useOverview";
import { StatusBadge } from "./widgets";

export default function AssignPage() {
  const { choices, def } = useRepoChoices();
  const [repo, setRepo] = useState("");
  const [cache, setCache] = useState<Record<string, { issues: Issue[]; note: string }>>({});
  const [picked, setPicked] = useState<string[]>([]);
  const cur = repo || def;
  const shown = (cur && cache[cur]) || null;
  const [phase, setPhase] = useState("");
  const [scanning, setScanning] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [assignPhase, setAssignPhase] = useState("");
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
    onSuccess: (d, target) => {
      setCache((c) => ({ ...c, [target ?? cur]: { issues: d.issues, note: d.scan_note } }));
      setPicked([]);
    },
    onError: (e: Error) => message.error(e.message),
    onSettled: () => setScanning(false),
  });

  useEffect(() => {
    if (!scanning || !cur) return;
    setPhase("正在准备重扫…");
    const timer = setInterval(() => {
      api
        .scanProgress(cur)
        .then((p) => {
          if (p.step && !p.stale) setPhase(p.step);
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
      const seen = new Set<string>();
      const deduped: Array<{ rule: string; path: string }> = [];
      for (const p of picked) {
        const [rule, path] = p.split("|");
        const k = `${rule}|${path}`;
        if (seen.has(k)) continue;
        seen.add(k);
        deduped.push({ rule, path });
      }
      return api.assign(cur, deduped);
    },
    onSuccess: (d) => {
      const actions = (d.decisions || []).map((x) => x.action);
      const opened = actions.filter((a) => a === "opened" || a === "already").length;
      message.success(`已指派 ${actions.length} 条，开请求 ${opened}，列表已刷新`);
      list.mutate();
    },
    onError: (e: Error) => message.error(e.message),
    onSettled: () => setAssigning(false),
  });

  useEffect(() => {
    if (!assigning || !cur) return;
    const timer = setInterval(() => {
      api
        .scanProgress(cur)
        .then((p) => {
          if (p.step && !p.stale) setAssignPhase(p.step);
        })
        .catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assigning, cur]);

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
      ellipsis: true,
      render: (v: string, r) => (
        <span title={v}>
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
      ),
    },
    {
      title: "可修",
      key: "eligible",
      width: 80,
      render: (_, r) => <StatusBadge tone={r.eligible ? "ok" : "mute"} text={r.eligible ? "可修" : "跳过"} />,
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
            }}
            options={choices.map((c) => ({ label: c.key, value: c.key }))}
          />
          <Button
            type="primary"
            loading={list.isPending}
            disabled={!cur}
            onClick={() => {
              setScanning(true);
              setPhase("正在准备重扫…");
              list.mutate(cur);
            }}
          >
            {list.isPending ? "正在重扫入库…" : shown ? "重新扫描" : "列出告警"}
          </Button>
          {list.isPending && (
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8, color: "#595959" }}>
              <Spin size="small" /> {phase || "正在准备重扫…"}
            </span>
          )}
        </Space>
        {load.isPending && !shown && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon message="正在读库里快照…" />
        )}
        {shown?.note && <Alert style={{ marginTop: 12 }} type="success" showIcon message={shown.note} />}
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
          rowKey={(r) => `${r.rule}|${r.path}|${r.line ?? 0}`}
          columns={columns}
          dataSource={visible}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          rowSelection={{
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys as string[]),
            getCheckboxProps: (r) => ({ disabled: !r.eligible }),
          }}
          locale={{ emptyText: cur ? "库里还没有这个项目的快照，点「重新扫描」扫一遍入库" : "选好项目后点「重新扫描」" }}
        />
        <Button
          type="primary"
          loading={assign.isPending}
          disabled={picked.length === 0}
          onClick={() => {
            setAssigning(true);
            setAssignPhase("正在准备指派…");
            assign.mutate();
          }}
        >
          指派给 Agent{picked.length > 0 ? `（${picked.length}）` : ""}
        </Button>
        {assign.isPending && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 8, marginLeft: 12, color: "#595959" }}>
            <Spin size="small" /> {assignPhase || "正在准备指派…"}
          </span>
        )}
      </Card>
    </Space>
  );
}
