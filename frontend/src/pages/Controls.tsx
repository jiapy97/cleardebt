import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Form, Input, Select, Space, Switch, Table, message } from "antd";
import { api } from "../lib/api";
import { useOverview } from "../lib/useOverview";

export default function ControlsPage() {
  const { data: overview } = useOverview();
  const qc = useQueryClient();
  const auto = (overview?.backlog_automation ?? {}) as Record<string, string | boolean>;
  const [form] = Form.useForm();

  const refresh = () => {
    message.success("已保存");
    qc.invalidateQueries({ queryKey: ["overview"] });
  };
  const fail = (e: Error) => message.error(e.message);

  const saveFlags = (patch: Record<string, boolean>) =>
    api.saveControls(patch).then(refresh, fail);

  const saveSched = useMutation({
    mutationFn: (v: Record<string, string | boolean>) =>
      api.saveControls({
        backlog_automation: {
          enabled: v.enabled,
          frequency: v.frequency,
          weekday: v.weekday,
          hour: v.hour,
          minute: v.minute,
          timezone: v.timezone,
          pause_when_open_mrs: (v.pause as string) || null,
        },
      }),
    onSuccess: refresh,
    onError: fail,
  });

  const bindings = (overview?.bindings ?? []) as Array<Record<string, unknown>>;
  const base = bindings.map((b) => ({
    key: String(b.sonar_key ?? ""),
    backlog: (b.backlog_fix as boolean) ?? true,
    request: (b.request_fix as boolean) ?? true,
    agent: (b.agent_mode as boolean) ?? false,
    automation: (b.automation as Record<string, unknown>) ?? {},
    override: !!b.automation && Object.keys(b.automation as object).length > 0,
  }));
  const [rows, setRows] = useState<typeof base | null>(null);
  const data = rows ?? base;
  const flip = (key: string, field: "backlog" | "request" | "agent" | "override") =>
    setRows((data).map((x) => (x.key === key ? { ...x, [field]: !x[field] } : x)));
  const saveProj = useMutation({
    mutationFn: () =>
      api.saveControls({
        project_switches: data.map((r) => ({
          sonar_key: r.key,
          backlog_fix: r.backlog,
          request_fix: r.request,
          agent_mode: r.agent,
          automation: r.override ? (Object.keys(r.automation).length ? r.automation : { enabled: true }) : {},
        })),
      }),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["overview"] });
      setRows(null);
      message.success("项目开关已保存");
    },
    onError: fail,
  });

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card title="总开关" extra="点一下立即生效">
        <Space direction="vertical" style={{ width: "100%" }}>
          {(
            [
              ["enabled", "总开关", "关掉之后，到点的那一轮不会开始。"],
              ["dry_run", "空跑", "打开之后，只出清算单，不开合并请求。"],
              ["retrieve", "检索旧例子", "打开之后，所有 LLM 可修规则会带上以前同规则的 L1 补丁片段。"],
              ["request_fix", "请求修复", "关掉之后，不对质量门失败的合并请求开修复请求。"],
            ] as const
          ).map(([k, title, desc]) => (
            <div key={k} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>
                <strong>{title}</strong>
                <div style={{ color: "#8c8c8c", fontSize: 12 }}>{desc}</div>
              </span>
              <Switch
                checked={!!overview?.[k as "enabled"]}
                onChange={(v) => saveFlags({ [k]: v })}
              />
            </div>
          ))}
        </Space>
      </Card>
      <Card title="定时清 backlog">
        <Form
          form={form}
          layout="inline"
          initialValues={{
            enabled: !!auto.enabled,
            frequency: (auto.frequency as string) || "daily",
            hour: String(auto.hour ?? 8),
            minute: String(auto.minute ?? 0),
            timezone: (auto.timezone as string) || "Asia/Shanghai",
            pause: auto.pause_when_open_mrs == null ? "" : String(auto.pause_when_open_mrs),
          }}
          onFinish={(v) => saveSched.mutate(v)}
        >
          <Form.Item label="自动清" name="enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="频率" name="frequency">
            <Select style={{ width: 100 }} options={[{ label: "每天", value: "daily" }, { label: "每周", value: "weekly" }]} />
          </Form.Item>
          <Form.Item label="时" name="hour">
            <Input style={{ width: 70 }} />
          </Form.Item>
          <Form.Item label="分" name="minute">
            <Input style={{ width: 70 }} />
          </Form.Item>
          <Form.Item label="时区" name="timezone">
            <Input style={{ width: 150 }} />
          </Form.Item>
          <Form.Item label="暂停上限" name="pause">
            <Input style={{ width: 100 }} placeholder="空=不限制" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit" loading={saveSched.isPending}>
              保存日程
            </Button>
          </Form.Item>
        </Form>
      </Card>
      <Card title="按项目开关">
        {data.length === 0 ? (
          "白名单有项目后，这里可以按项目开关。"
        ) : (
          <>
            <Table
              rowKey="key"
              pagination={false}
              dataSource={data}
              columns={[
                { title: "项目", dataIndex: "key" },
                {
                  title: "Backlog",
                  dataIndex: "backlog",
                  render: (v: boolean, r: { key: string }) => (
                    <Switch checked={v} onChange={() => flip(r.key, "backlog")} />
                  ),
                },
                {
                  title: "请求修复",
                  dataIndex: "request",
                  render: (v: boolean, r: { key: string }) => (
                    <Switch checked={v} onChange={() => flip(r.key, "request")} />
                  ),
                },
                {
                  title: "自主工具调用",
                  dataIndex: "agent",
                  render: (v: boolean, r: { key: string }) => (
                    <Switch checked={v} onChange={() => flip(r.key, "agent")} />
                  ),
                },
              ]}
            />
            <Button style={{ marginTop: 12 }} type="primary" loading={saveProj.isPending} onClick={() => saveProj.mutate()}>
              保存项目开关
            </Button>
          </>
        )}
      </Card>
    </Space>
  );
}
