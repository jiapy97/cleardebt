import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Select, Space, Table, message } from "antd";
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

  const list = useMutation({
    mutationFn: (target?: string) => api.listIssues(target ?? cur),
    onSuccess: (d, target) => {
      setCache((c) => ({ ...c, [target ?? cur]: { issues: d.issues, note: d.scan_note } }));
      setPicked([]);
    },
    onError: (e: Error) => message.error(e.message),
  });

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
    mutationFn: () =>
      api.assign(
        cur,
        picked.map((p) => {
          const [rule, path] = p.split("|");
          return { rule, path };
        }),
      ),
    onSuccess: (d) => {
      const actions = (d.decisions || []).map((x) => x.action);
      const opened = actions.filter((a) => a === "opened" || a === "already").length;
      message.success(`已指派 ${actions.length} 条，开请求 ${opened}，列表已刷新`);
      list.mutate();
    },
    onError: (e: Error) => message.error(e.message),
  });

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
      title: "说明",
      dataIndex: "message",
      key: "message",
      ellipsis: true,
      render: (v: string, r) => <span title={v}>{r.message_zh || v}</span>,
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
          <Button type="primary" loading={list.isPending} disabled={!cur} onClick={() => list.mutate(cur)}>
            {list.isPending ? "正在重扫入库…" : shown ? "重新扫描" : "列出告警"}
          </Button>
        </Space>
        {load.isPending && !shown && (
          <Alert style={{ marginTop: 12 }} type="info" showIcon message="正在读库里快照…" />
        )}
        {shown?.note && <Alert style={{ marginTop: 12 }} type="success" showIcon message={shown.note} />}
      </Card>
      <Card title={`告警列表${shown ? `（${shown.issues.length} 条）` : ""}`}>
        <Table<Issue>
          rowKey={(r) => `${r.rule}|${r.path}`}
          columns={columns}
          dataSource={shown?.issues ?? []}
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
          onClick={() => assign.mutate()}
        >
          指派给 Agent{picked.length > 0 ? `（${picked.length}）` : ""}
        </Button>
      </Card>
    </Space>
  );
}
