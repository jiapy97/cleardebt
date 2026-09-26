import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Select, Space, Table, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import { api, issueId, issueSelection, type Issue, type Session, type SessionEvent } from "../lib/api";
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
  const qc = useQueryClient();
  const cancel = useMutation({
    mutationFn: api.cancelSession,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sessions"] }),
    onError: (error: Error) => message.error(error.message),
  });
  const sessions: Session[] = data?.sessions ?? [];
  return (
    <Table<Session>
      rowKey="id"
      pagination={{ pageSize: 15, showSizeChanger: false }}
      dataSource={sessions}
      locale={{ emptyText: "还没有会话" }}
      expandable={{ expandedRowRender: (session) => <SessionEvents session={session} /> }}
      columns={[
        { title: "时间（北京）", dataIndex: "created_at", key: "t", width: 150 },
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
            ) : v === "cancelled" ? (
              <StatusBadge tone="x" text="已取消" />
            ) : (
              <StatusBadge tone="x" text="排队" />
            ),
        },
        {
          title: "说明",
          key: "note",
          ellipsis: true,
          render: (_, s) => {
            const d = (s.details ?? {}) as { warning?: string; error?: string; decisions?: Array<{ fix_method?: string; agent_tool_count?: number }> };
            const mechanical = d.decisions?.length === 1 && d.decisions[0].fix_method === "mechanical" && !d.decisions[0].agent_tool_count;
            const note = d.warning ?? d.error ?? (mechanical ? "机械规则修复，未调用模型工具" : s.finished_at ? `结束于 ${s.finished_at}` : "—");
            return <span title={note}>{note}</span>;
          },
        },
        {
          title: "操作",
          key: "action",
          width: 85,
          render: (_, s) => ["pending", "running"].includes(s.status) ? (
            <Button size="small" onClick={() => cancel.mutate(s.id)}>取消</Button>
          ) : null,
        },
      ]}
    />
  );
}

function SessionEvents({ session }: { session: Session }) {
  const { data, isLoading } = useQuery({
    queryKey: ["session-events", session.id],
    queryFn: () => api.sessionEvents(session.id),
    refetchInterval: ["pending", "running"].includes(session.status) ? 5_000 : false,
  });
  const events: SessionEvent[] = data?.events ?? [];
  const sourceSessions = data?.source_session_ids ?? [];
  const decisions = ((session.details ?? {}).decisions ?? []) as Array<{
    rule?: string;
    path?: string;
    level?: string;
    action?: string;
    reason?: string;
    fix_method?: string;
    agent_tool_count?: number;
    web_url?: string;
  }>;
  const decisionRows = decisions.map((decision, index) => ({
    id: -(index + 1),
    created_at: session.finished_at || session.created_at,
    fingerprint: "",
    kind: "decision",
    tool: decision.fix_method === "mechanical" ? "机械规则" : "处理结论",
    summary: `${decision.rule || "告警"} ${decision.path || ""}：${decision.level || "—"}，${{
      opened: "已创建合并请求", already: "合并请求已存在", dry_run: "空跑",
      held: "暂缓", no_mr: "未创建合并请求",
    }[decision.action || ""] || decision.action || "已处理"}。${decision.reason || ""}`,
    details: {},
    web_url: decision.web_url,
  }));
  const rows = [...events, ...decisionRows];
  const mechanicalOnly = events.length === 0 && decisions.length > 0
    && decisions.every((decision) => decision.fix_method === "mechanical" && !decision.agent_tool_count);
  return (
    <Space direction="vertical" size="small" style={{ width: "100%" }}>
      {!isLoading && sourceSessions.length > 0 && (
        <Alert type="info" showIcon message={`本次没有重新调用模型，沿用了已过闸的结果。下面是会话 #${sourceSessions.join("、#")} 的工具记录。`} />
      )}
      {!isLoading && mechanicalOnly && <Alert type="info" showIcon message="本次由内置机械规则完成修复，没有调用大模型工具；下方是实际处理结果。" />}
      {!isLoading && !mechanicalOnly && sourceSessions.length === 0 && events.length === 0 && decisions.length > 0 &&
        <Alert type="info" showIcon message="本次没有工具调用明细；下方是会话保存的处理结果。" />}
      <Table<SessionEvent & { web_url?: string }>
        size="small"
        rowKey="id"
        loading={isLoading}
        pagination={false}
        dataSource={rows}
        locale={{ emptyText: "这条会话没有步骤或处理结论记录。" }}
        columns={[
          { title: "时间（北京）", dataIndex: "created_at", width: 180 },
          { title: "步骤", dataIndex: "tool", width: 160 },
          { title: "结果", dataIndex: "summary", render: (summary: string, row) => <>
            {summary}{row.web_url && <> <a href={row.web_url} target="_blank" rel="noreferrer">查看合并请求</a></>}
          </> },
        ]}
      />
    </Space>
  );
}
