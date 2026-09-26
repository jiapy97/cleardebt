import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Select, Space, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api, issueId, issueSelection, type Issue, type Session } from "../lib/api";
import { useRepoChoices } from "../lib/useOverview";
import { StatusBadge } from "./widgets";

export default function MrsPage() {
  const { choices, def } = useRepoChoices();
  const [repo, setRepo] = useState("");
  const [iid, setIid] = useState("");
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [status, setStatus] = useState("");
  const cur = repo || def;

  const list = useMutation({
    mutationFn: () => api.mrIssues(cur, Number(iid)),
    onSuccess: (d) => {
      setIssues(d.issues);
      setPicked([]);
      setStatus(`源分支 ${d.merge_request?.source_branch || ""}；告警 ${d.issues.length} 条。修复请求会打向该源分支。`);
    },
    onError: (e: Error) => {
      setStatus(e.message);
      message.error(e.message);
    },
  });
  const offer = useMutation({
    mutationFn: () => api.mrOffer(cur, Number(iid)),
    onSuccess: (d) => setStatus(`已在合并请求下留言（note ${d.note_id}）。`),
    onError: (e: Error) => {
      setStatus(e.message);
      message.error(e.message);
    },
  });
  const run = useMutation({
    mutationFn: () =>
      api.mrRemediate(
        cur,
        Number(iid),
        (issues ?? []).filter((row) => picked.includes(issueId(row))).map(issueSelection),
      ),
    onSuccess: (d) => {
      setStatus(d.already_running
        ? "这条请求正在修复，去 Agent 活动查看。"
        : `已开始会话 #${d.session_id}。去 Agent 活动查看结果。`);
      if (!d.already_running) setPicked([]);
    },
    onError: (e: Error) => {
      setStatus(e.message);
      message.error(e.message);
    },
  });

  const columns: ColumnsType<Issue> = [
    { title: "规则", dataIndex: "rule", key: "rule", width: 180 },
    { title: "文件", dataIndex: "path", key: "path", width: 160 },
    {
      title: "行",
      dataIndex: "line",
      key: "line",
      width: 70,
      render: (v: number) => (v ? `L${v}` : "—"),
    },
    {
      title: "是否可以指派给 Agent",
      key: "eligible",
      width: 170,
      render: (_, r) => <StatusBadge tone="x" text={r.eligible ? "是" : "否"} />,
    },
    { title: "最新状态", key: "status", width: 170, render: (_, r) => <StatusBadge status={r.status} /> },
  ];

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card>
        <Space wrap>
          <Select
            style={{ width: 220 }}
            value={cur || undefined}
            onChange={(value) => {
              setRepo(value);
              setIssues(null);
              setPicked([]);
              setStatus("");
            }}
            options={choices.map((c) => ({ label: c.key, value: c.key }))}
          />
          <Input
            style={{ width: 160 }}
            type="number"
            min={1}
            placeholder="合并/拉取请求号"
            value={iid}
            onChange={(e) => {
              setIid(e.target.value);
              setIssues(null);
              setPicked([]);
              setStatus("");
            }}
          />
          <Button type="primary" loading={list.isPending} disabled={!cur || !iid} onClick={() => list.mutate()}>
            列出告警
          </Button>
          <Button loading={offer.isPending} disabled={!cur || !iid} onClick={() => offer.mutate()}>
            在请求下留言
          </Button>
        </Space>
        {status && <Alert style={{ marginTop: 12 }} type="info" showIcon message={status} />}
      </Card>
      <Card title="请求上的告警">
        <Table<Issue>
          rowKey={issueId}
          columns={columns}
          dataSource={issues ?? []}
          pagination={false}
          rowSelection={{
            selectedRowKeys: picked,
            onChange: (keys) => setPicked(keys as string[]),
            getCheckboxProps: (r) => ({ disabled: !r.eligible }),
          }}
          locale={{ emptyText: "填好项目和合并请求号后点「列出告警」" }}
        />
        <Button
          style={{ marginTop: 12 }}
          type="primary"
          loading={run.isPending}
          disabled={picked.length === 0}
          onClick={() => run.mutate()}
        >
          运行修复 Agent{picked.length > 0 ? `（${picked.length}）` : ""}
        </Button>
      </Card>
    </Space>
  );
}

const sourceLabel: Record<string, string> = { manual: "手动指派", scheduled: "定时", request_fix: "请求修复" };

export function ActivityTable() {
  const { data } = useQuery({ queryKey: ["sessions"], queryFn: api.sessions, refetchInterval: 10_000 });
  const sessions: Session[] = data?.sessions ?? [];
  return (
    <Table<Session>
      rowKey="id"
      pagination={{ pageSize: 15, showSizeChanger: false }}
      dataSource={sessions}
      locale={{ emptyText: "还没有会话" }}
      columns={[
        { title: "时间", dataIndex: "created_at", key: "t", width: 130 },
        {
          title: "来源",
          dataIndex: "source",
          key: "s",
          width: 100,
          render: (v: string) => sourceLabel[v] ?? v,
        },
        { title: "项目", dataIndex: "repo", key: "r", width: 110 },
        { title: "条数", dataIndex: "issue_count", key: "c", width: 70 },
        {
          title: "状态",
          dataIndex: "status",
          key: "st",
          width: 90,
          render: (v: string) =>
            v === "completed" ? (
              <StatusBadge tone="ok" text="完成" />
            ) : v === "failed" ? (
              <StatusBadge tone="err" text="失败" />
            ) : v === "running" ? (
              <StatusBadge tone="run" text="运行" />
            ) : (
              <StatusBadge tone="x" text="排队" />
            ),
        },
        {
          title: "说明",
          key: "note",
          ellipsis: true,
          render: (_, s) => {
            const d = (s.details ?? {}) as { warning?: string; error?: string };
            return <span title={d.warning ?? d.error ?? ""}>{d.warning ?? d.error ?? (s.finished_at ? `结束于 ${s.finished_at}` : "—")}</span>;
          },
        },
      ]}
    />
  );
}
