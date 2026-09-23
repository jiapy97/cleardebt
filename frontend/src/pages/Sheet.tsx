import { useQuery } from "@tanstack/react-query";
import { Card, Table } from "antd";
import { api } from "../lib/api";
import { StatusBadge } from "./widgets";

interface Decision {
  rule?: string;
  path?: string;
  level?: string;
  action?: string;
  reason?: string;
  web_url?: string;
  suggestion?: { old_string?: string; new_string?: string };
}

const actionLabel: Record<string, string> = {
  already: "已经开过请求",
  opened: "这一轮开了请求",
  held: "留下次再开",
  no_mr: "不开请求",
  dry_run: "空跑，不开请求",
  open: "准备开请求",
};

export default function SheetPage() {
  const { data, isLoading } = useQuery({ queryKey: ["sheet"], queryFn: api.latestSheet });
  const sheet = (data ?? null) as {
    repo?: string;
    created_at?: string;
    dry_run?: boolean;
    decisions?: Decision[];
  } | null;
  const decisions = sheet?.decisions ?? [];
  return (
    <Card
      title="清算单"
      extra={sheet ? `${sheet.repo} · ${sheet.created_at} · ${sheet.dry_run ? "空跑" : "实跑"}` : ""}
      loading={isLoading}
    >
      <Table<Decision>
        rowKey={(_, i) => String(i)}
        dataSource={decisions}
        pagination={false}
        locale={{ emptyText: "还没有跑过一轮" }}
        expandable={{
          expandedRowRender: (d) =>
            d.suggestion ? (
              <div style={{ display: "grid", gap: 8, maxWidth: 560 }}>
                <pre style={{ background: "#18181b", color: "#fafafa", padding: 12, borderRadius: 8, overflowX: "auto" }}>
                  {d.suggestion.old_string}
                </pre>
                <pre style={{ background: "#052e16", color: "#ecfdf5", padding: 12, borderRadius: 8, overflowX: "auto" }}>
                  {d.suggestion.new_string}
                </pre>
              </div>
            ) : (
              "无建议片段"
            ),
        }}
        columns={[
          { title: "规则", dataIndex: "rule", key: "rule", width: 170, render: (v: string) => <strong>{v}</strong> },
          { title: "文件", dataIndex: "path", key: "path", width: 150 },
          {
            title: "级别",
            dataIndex: "level",
            key: "level",
            width: 90,
            render: (v: string) => <StatusBadge tone={v} text={v} />,
          },
          {
            title: "这一轮",
            dataIndex: "action",
            key: "action",
            width: 130,
            render: (v: string) => (
              <StatusBadge tone={v === "opened" || v === "already" ? "ok" : "x"} text={actionLabel[v] ?? v} />
            ),
          },
          {
            title: "说明",
            key: "reason",
            ellipsis: true,
            render: (_, d) => (
              <span title={d.reason}>
                {d.reason}{" "}
                {d.web_url && (
                  <a href={d.web_url} target="_blank" rel="noreferrer">
                    查看合并请求
                  </a>
                )}
              </span>
            ),
          },
        ]}
      />
    </Card>
  );
}
