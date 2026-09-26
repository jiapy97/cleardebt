import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Space, Tag, Typography } from "antd";
import { api, type Suggestion } from "../lib/api";
import { StatusBadge, levelLabel } from "./widgets";

function fingerprintFromHash(): string {
  const query = window.location.hash.split("?")[1] ?? "";
  return new URLSearchParams(query).get("fp") ?? "";
}

const LEVEL_HINTS: Record<string, string> = {
  L1: "告警消失了，检查都过了，可以合并。",
  L2: "改法通过了重扫和测试，但改动的行没有测试覆盖，请审一下再用。",
  L3: "这次改动没通过检查，下面的改法仅供参考，不要直接套用。",
};

function DiffBlock({ diff }: { diff: string }) {
  return (
    <pre style={{ margin: 0, padding: 12, borderRadius: 8, background: "#fafafa", overflowX: "auto", fontSize: 13, lineHeight: 1.5 }}>
      {diff.split("\n").map((line, index) => {
        const header = line.startsWith("+++") || line.startsWith("---");
        const style = header
          ? { color: "#71717a" }
          : line.startsWith("@@")
            ? { color: "#2563eb" }
            : line.startsWith("+")
              ? { background: "#dcfce7", color: "#166534" }
              : line.startsWith("-")
                ? { background: "#fee2e2", color: "#991b1b" }
                : undefined;
        return (
          <div key={index} style={style}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}

function CheckList({ checks }: { checks: Suggestion["checks"] }) {
  if (!checks.length) return <Typography.Text type="secondary">这次运行的检查记录已经清掉了，只剩结论。</Typography.Text>;
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {checks.map((check) => (
        <div key={check.name}>
          <Tag color={check.ok === null ? "default" : check.ok ? "green" : "red"}>
            {check.ok === null ? "跳过" : check.ok ? "通过" : "没通过"}
          </Tag>
          <strong>{check.name}</strong>
          <span style={{ marginLeft: 8 }}>{check.detail}</span>
        </div>
      ))}
    </Space>
  );
}

export default function SuggestionPage() {
  const [fingerprint, setFingerprint] = useState(fingerprintFromHash);
  useEffect(() => {
    const onHash = () => setFingerprint(fingerprintFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const { data, error, isLoading } = useQuery({
    queryKey: ["suggestion", fingerprint],
    queryFn: () => api.suggestion(fingerprint),
    enabled: !!fingerprint,
    retry: false,
  });

  if (!fingerprint) return <Alert type="warning" showIcon message="没有指定是哪条告警的修复建议。" />;
  if (error) return <Alert type="error" showIcon message="读取修复建议失败" description={(error as Error).message} />;
  if (isLoading || !data) return <Card loading style={{ minHeight: 200 }} />;

  const hint = LEVEL_HINTS[data.level];
  const failedModels = data.model_attempts.filter((attempt) => !attempt.ok);
  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {hint && <Alert type={data.level === "L1" ? "success" : "warning"} showIcon message={`${levelLabel(data.level)}：${hint}`} />}
      <Card
        title="文字说明"
        extra={data.mr_url && (
          <Button type="primary" href={data.mr_url} target="_blank" rel="noreferrer">
            查看合并请求
          </Button>
        )}
      >
        <Descriptions column={1} size="small" labelStyle={{ width: 110 }}>
          <Descriptions.Item label="规则">
            <Typography.Text copyable>{data.rule}</Typography.Text>
            <span style={{ marginLeft: 8 }}>{data.rule_name}</span>
          </Descriptions.Item>
          <Descriptions.Item label="位置">
            {data.path}
            {data.line ? `，第 ${data.line} 行` : ""}
          </Descriptions.Item>
          {data.message && (
            <Descriptions.Item label="告警">
              {data.message_zh && data.message_zh !== data.message ? (
                <>
                  {data.message_zh}
                  <br />
                  <Typography.Text type="secondary">{data.message}</Typography.Text>
                </>
              ) : (
                data.message
              )}
            </Descriptions.Item>
          )}
          <Descriptions.Item label="结果">
            <StatusBadge tone={data.level} text={levelLabel(data.level)} />
            <span style={{ marginLeft: 8 }}>{data.reason}</span>
          </Descriptions.Item>
          {data.fix_method && (
            <Descriptions.Item label="修复方式">
              {data.fix_method}
              {data.model_used ? `（模型 ${data.model_used}）` : ""}
            </Descriptions.Item>
          )}
          {failedModels.length > 0 && (
            <Descriptions.Item label="失败的尝试">
              {failedModels.map((attempt, index) => (
                <div key={index}>
                  {attempt.model}：{attempt.error}
                </div>
              ))}
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>
      <Card title="检查结果">
        <CheckList checks={data.checks} />
      </Card>
      <Card title="修改建议（diff）">
        <Space direction="vertical" style={{ width: "100%" }}>
          {data.diff_scope === "snippet" && (
            <Alert type="info" showIcon message="这次运行的完整文件已经清掉了，下面只是保存下来的修改片段，行号不是文件里的真实行号。" />
          )}
          {data.diffs.map((item) => (
            <div key={item.path}>
              <Typography.Text strong>{item.path}</Typography.Text>
              <div style={{ marginTop: 8 }}>
                <DiffBlock diff={item.diff} />
              </div>
            </div>
          ))}
        </Space>
      </Card>
    </Space>
  );
}
