import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, Select, Space, Table, Tag, message } from "antd";
import { api } from "../lib/api";

interface RuleRow {
  key: string;
  number: string;
  tier: string;
  label: string;
  pinned: boolean;
  zh_source: string;
}

const tierTag: Record<string, string> = { A: "green", B: "blue", C: "orange", unknown: "default" };

export default function RulesPage() {
  const [q, setQ] = useState("S107");
  const [drafts, setDrafts] = useState<Record<string, { tier: string; zh: string }>>({});
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
  const translate = useMutation({
    mutationFn: () => api.rulesTranslate(20),
    onSuccess: (d) => {
      message.success(`机翻了 ${d.translated} 条（标了机翻，人工改过为准）`);
      invalidate();
    },
    onError: (e: Error) => message.error(e.message),
  });
  const save = (r: RuleRow) => {
    const d = drafts[r.number] ?? { tier: tierFor(r), zh: zhFor(r) };
    api
      .rulePin(r.number, d.tier, d.zh)
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

  const tierFor = (r: RuleRow) => (drafts[r.number]?.tier ?? (r.tier === "unknown" ? "" : r.tier));
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
          <Button loading={translate.isPending} onClick={() => translate.mutate()}>
            机翻缺失的中文（20 条）
          </Button>
        </Space>
        <div style={{ marginTop: 8, color: "#8c8c8c", fontSize: 12 }}>
          共 {data?.total ?? 0} 条（Sonar 全量）。档位空 = 跟随自动策略；中文空 = 显示英文原名。机翻的标黄，人工保存后摘标。
        </div>
      </Card>
      <Card title="规则">
        <Table<RuleRow>
          rowKey="key"
          loading={isLoading}
          dataSource={rows}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          columns={[
            { title: "规则", dataIndex: "key", key: "key", width: 200 },
            {
              title: "档位",
              key: "tier",
              width: 200,
              render: (_, r) => (
                <Space>
                  <Tag color={tierTag[r.tier] ?? "default"}>{r.tier === "unknown" ? "自动" : r.tier}</Tag>
                  <Select
                    style={{ width: 110 }}
                    placeholder="跟随自动"
                    value={tierFor(r) || undefined}
                    onChange={(v) => setDrafts((p) => ({ ...p, [r.number]: { tier: v, zh: zhFor(r) } }))}
                    options={[
                      { label: "A 可修", value: "A" },
                      { label: "B 可修", value: "B" },
                      { label: "C 跳过", value: "C" },
                    ]}
                  />
                </Space>
              ),
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
                      setDrafts((p) => ({ ...p, [r.number]: { tier: tierFor(r), zh: e.target.value } }))
                    }
                  />
                  {r.zh_source === "mt" && !drafts[r.number] && <Tag color="gold">机翻</Tag>}
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
