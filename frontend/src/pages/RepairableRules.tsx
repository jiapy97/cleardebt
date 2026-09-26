import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Input, Space, Statistic, Table, Tag, Typography } from "antd";
import { api, type RepairableRulesResponse } from "../lib/api";

type Rule = RepairableRulesResponse["rules"][number];

export default function RepairableRulesPage() {
  const [search, setSearch] = useState("");
  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["repairable-rules"],
    queryFn: api.repairableRules,
    staleTime: 60_000,
    retry: false,
  });
  const rows = useMemo(() => {
    const wanted = search.trim().toLowerCase();
    return (data?.rules ?? [])
      .filter((rule) => !wanted || `${rule.key} ${rule.name} ${rule.projects.join(" ")}`.toLowerCase().includes(wanted))
      .sort((a, b) => b.issue_count - a.issue_count || a.key.localeCompare(b.key));
  }, [data, search]);
  const listMode = data?.mode === "ai_codefix_list";

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {error && <Alert type="error" showIcon message="读取可修规则失败" description={(error as Error).message} />}
      {data && (
        <Alert
          type="info"
          showIcon
          message={listMode ? "来源：已配置的 Sonar AI CodeFix 清单" : "来源：当前 Sonar 扫描的 Quick Fix 标记"}
          description={listMode
            ? "按完整规则键匹配。这里显示 Agent 已接入语言中的清单规则；命中告警数只统计当前打开的 Sonar 告警。"
            : "这里汇总当前打开的告警中 Sonar 标记 quickFixAvailable=true 的规则。同一规则的其他告警仍需逐条看标记；这不是 Sonar AI CodeFix 的完整名单。"}
        />
      )}
      <Card>
        <Space size="large" wrap>
          <Statistic title={listMode ? "清单内已接入规则" : "当前告警涉及的 Quick Fix 规则"} value={data?.rule_count ?? 0} suffix="条" />
          <Statistic title="命中告警" value={data?.eligible_issue_count ?? 0} suffix="条" />
          <Statistic title="打开的 Sonar 告警" value={data?.open_issue_count ?? 0} suffix="条" />
        </Space>
        {data && <Typography.Text type="secondary" style={{ display: "block", marginTop: 12 }}>
          查询时间：{new Date(data.checked_at).toLocaleString("zh-CN")}
        </Typography.Text>}
      </Card>
      <Card
        title="规则清单"
        extra={<Space>
          <Input.Search allowClear placeholder="搜索规则、名称或项目" onChange={(event) => setSearch(event.target.value)} style={{ width: 240 }} />
          <Button loading={isFetching} onClick={() => refetch()}>从 Sonar 刷新</Button>
        </Space>}
      >
        <Table<Rule>
          rowKey="key"
          loading={isLoading}
          dataSource={rows}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{ emptyText: data ? "当前没有符合条件的规则" : "暂无数据" }}
          columns={[
            { title: "规则键", dataIndex: "key", key: "key", width: 210, render: (key: string) => <Typography.Text copyable>{key}</Typography.Text> },
            { title: "Sonar 规则名称", dataIndex: "name", key: "name", ellipsis: true, render: (name: string) => name || "—" },
            { title: "语言", dataIndex: "language", key: "language", width: 140, render: (value: string) => <Tag>{value}</Tag> },
            { title: "命中告警", dataIndex: "issue_count", key: "issue_count", width: 110, sorter: (a, b) => a.issue_count - b.issue_count },
            { title: "涉及项目", dataIndex: "projects", key: "projects", width: 250, ellipsis: true, render: (projects: string[]) => projects.length ? projects.join("、") : "—" },
          ]}
        />
      </Card>
    </Space>
  );
}
