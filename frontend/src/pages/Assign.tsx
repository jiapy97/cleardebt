import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Card, Select, Space, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api, type Issue } from "../lib/api";
import { useRepoChoices } from "../lib/useOverview";
import { StatusBadge } from "./widgets";

export default function AssignPage() {
  const { choices, def } = useRepoChoices();
  const [repo, setRepo] = useState("");
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const cur = repo || def;
  const autoRan = useRef(false);
  useEffect(() => {
    if (autoRan.current || !cur || issues !== null) return;
    autoRan.current = true;
    list.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cur]);

  const list = useMutation({
    mutationFn: () => api.listIssues(cur),
    onSuccess: (d) => {
      setIssues(d.issues);
      setNote(d.scan_note);
      setPicked([]);
    },
    onError: (e: Error) => message.error(e.message),
  });
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
      render: (v: string) => <span title={v}>{v}</span>,
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
            onChange={setRepo}
            options={choices.map((c) => ({ label: c.key, value: c.key }))}
          />
          <Button type="primary" loading={list.isPending} disabled={!cur} onClick={() => list.mutate()}>
            {list.isPending ? "正在重扫并列出…" : "列出告警"}
          </Button>
        </Space>
        {note && <Alert style={{ marginTop: 12 }} type="success" showIcon message={note} />}
      </Card>
      <Card title={`告警列表${issues ? `（${issues.length} 条）` : ""}`}>
        <Table<Issue>
          rowKey={(r) => `${r.rule}|${r.path}`}
          columns={columns}
          dataSource={issues ?? []}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          rowSelection={{
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys as string[]),
            getCheckboxProps: (r) => ({ disabled: !r.eligible }),
          }}
          locale={{ emptyText: "选好项目后点「列出告警」" }}
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
