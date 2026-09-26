import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, Space, Table, Tag, Tooltip, message } from "antd";
import { api } from "../lib/api";

interface RuleRow {
  key: string;
  number: string;
  name: string;
  type: string;
  severity: string;
  impacts: Array<{ softwareQuality?: string; severity?: string }>;
  clean_code_attribute: string;
  tier: string;
  ai_codefix_listed: boolean | null;
  label: string;
  pinned: boolean;
  zh_source: string;
}

function Verdict({ tier, listEnabled, listed }: { tier: string; listEnabled: boolean; listed: boolean | null }) {
  if (!listEnabled) return <Tooltip title="尚未配置 Sonar AI CodeFix 清单，Agent 不会修复 Sonar 告警"><Tag>清单未配置</Tag></Tooltip>;
  if (listed && tier === "unknown") return <Tooltip title="清单内，但 Agent 尚未接入此语言"><Tag>Agent 未接入</Tag></Tooltip>;
  return <Tooltip title={listed ? "在已配置的 Sonar AI CodeFix 清单内" : "不在已配置的 Sonar AI CodeFix 清单内"}>
    <Tag color={listed ? "green" : "orange"}>{listed ? "清单内" : "清单外"}</Tag>
  </Tooltip>;
}

export default function RulesPage() {
  const [q, setQ] = useState("S107");
  const [drafts, setDrafts] = useState<Record<string, { zh: string }>>({});
  const qc = useQueryClient();
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["rules", q],
    queryFn: () => api.rulesList(q),
  });
  const rows: RuleRow[] = data?.rules ?? [];

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["rules"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const refresh = useMutation({
    mutationFn: api.rulesRefresh,
    onSuccess: (d) => {
      message.success(`已从 Sonar 拉取 ${d.count} 条规则`);
      refetch();
    },
    onError: (e: Error) => message.error(e.message),
  });
  const save = (r: RuleRow) => {
    const d = drafts[r.number] ?? { zh: zhFor(r) };
    api
      .rulePin(r.number, d.zh)
      .then(() => {
        message.success(`${r.number} 已保存`);
        setDrafts((prev) => {
          const next = { ...prev };
          delete next[r.number];
          return next;
        });
        invalidate();
      })
      .catch((e: Error) => message.error(e.message));
  };

    const zhFor = (r: RuleRow) => (drafts[r.number]?.zh ?? (r.label.startsWith(r.number) ? "" : r.label));

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card>
        <Space wrap>
          <Input.Search
            style={{ width: 260 }}
            placeholder="搜规则号，如 S107"
            defaultValue={q}
            enterButton="搜索"
            onSearch={(v) => setQ(v)}
          />
          <Button loading={refresh.isPending} onClick={() => refresh.mutate()}>
            从 Sonar 刷新
          </Button>
          <Button
            onClick={() =>
              message.info("机翻已下线：中文名请亲手写，不写就显示 Sonar 英文原名。")
            }
          >
            中文名说明
          </Button>
        </Space>
        <div style={{ marginTop: 8, color: "#8c8c8c", fontSize: 12 }}>
          共 {data?.total ?? 0} 条（Sonar 全量）。类型/严重度/影响面/英文名全部是 Sonar 原文；{data?.ai_codefix_list_enabled ? "可修资格按已配置的 Sonar AI CodeFix 清单逐条匹配。" : "当前未配置 AI CodeFix 清单，Sonar 告警不能指派修复。"}中文名你可以亲手写，不写就显示英文。
        </div>
      </Card>
      <Card title="规则">
        <Table<RuleRow>
          rowKey="key"
          loading={isLoading}
          dataSource={rows}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: "规则", dataIndex: "key", key: "key", width: 170 },
            {
              title: "英文名（Sonar 原文）",
              dataIndex: "name",
              key: "name",
              ellipsis: true,
            },
            {
              title: "结论",
              key: "tier",
              width: 300,
              render: (_, r) => <Verdict tier={r.tier} listEnabled={!!data?.ai_codefix_list_enabled} listed={r.ai_codefix_listed} />,
            },
            {
              title: "中文名",
              key: "zh",
              render: (_, r) => (
                <Space>
                  <Input
                    style={{ width: 260 }}
                    placeholder={r.label}
                    value={drafts[r.number]?.zh ?? ""}
                    onChange={(e) =>
                      setDrafts((p) => ({ ...p, [r.number]: { zh: e.target.value } }))
                    }
                  />
                  {r.zh_source === "mt" && !drafts[r.number] && <Tag color="gold">旧机翻</Tag>}
                  {r.pinned && r.zh_source !== "mt" && <Tag color="green">人工</Tag>}
                </Space>
              ),
            },
            {
              title: "操作",
              key: "op",
              width: 90,
              render: (_, r) =>
                drafts[r.number] ? <a onClick={() => save(r)}>保存</a> : <span style={{ color: "#bfbfbf" }}>—</span>,
            },
          ]}
        />
      </Card>
    </Space>
  );
}
