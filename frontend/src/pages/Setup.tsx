import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Form, Input, Space, message } from "antd";
import { api } from "../lib/api";
import { useOverview } from "../lib/useOverview";
import BindingsTable from "./Bindings";

export default function SetupPage() {
  const { data: overview } = useOverview();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [picked, setPicked] = useState<string[] | null>(null);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [center, setCenter] = useState<{ ok: boolean; text: string; key: number } | null>(null);

  useEffect(() => {
    if (!center) return;
    const timer = setTimeout(() => setCenter(null), 4500);
    return () => clearTimeout(timer);
  }, [center]);
  const choices = overview?.repo_choices ?? [];
  const selected = picked ?? choices.filter((c) => c.selected).map((c) => c.key);

  useEffect(() => {
    if (!overview) return;
    const patch: Record<string, string> = {};
    const incoming: Record<string, string | undefined> = {
      sonar_url: overview.sonar_url,
      sonar_token: overview.sonar_token || undefined,
      gitlab_token: overview.gitlab_token || undefined,
      llm_token: overview.llm_token || undefined,
      bindings: overview.binding_lines || undefined,
    };
    for (const [k, v] of Object.entries(incoming)) {
      if (v && !form.getFieldValue(k)) patch[k] = v;
    }
    if (Object.keys(patch).length > 0) form.setFieldsValue(patch);
  }, [overview, form]);

  const onFinish = (v: Record<string, string>) => {
    setResult(null);
    api
      .saveSetup({
        sonar_url: v.sonar_url,
        sonar_token: v.sonar_token || "",
        gitlab_token: v.gitlab_token || "",
        llm_token: v.llm_token || "",
        whitelist: selected,
        project_keys: v.project_keys || "",
      })
      .then(() => {
        const text = "已保存接入，白名单与绑定已生效。";
        message.success(text);
        setResult({ ok: true, text });
        setCenter({ ok: true, text, key: Date.now() });
        qc.invalidateQueries({ queryKey: ["overview"] });
      })
      .catch((e: Error) => {
        const text = `没存上：${e.message}`;
        message.error(text);
        setResult({ ok: false, text });
        setCenter({ ok: false, text, key: Date.now() });
      });
  };

  return (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <BindingsTable />
      <Card title="接入配置">
      {center && (
        <div
          key={center.key}
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 2000,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "rgba(0,0,0,0.25)",
            pointerEvents: "auto",
          }}
          onClick={() => setCenter(null)}
        >
          <div
            style={{
              maxWidth: 480,
              margin: 24,
              background: "#fff",
              borderRadius: 12,
              padding: "20px 24px",
              boxShadow: "0 8px 32px rgba(0,0,0,0.25)",
              display: "flex",
              gap: 12,
              alignItems: "flex-start",
              fontSize: 15,
            }}
          >
            <span style={{ fontSize: 24, lineHeight: 1.4 }}>{center.ok ? "✅" : "❌"}</span>
            <span>
              <strong>{center.ok ? "保存成功" : "保存失败"}</strong>
              <div style={{ marginTop: 4, color: "#595959" }}>{center.text}</div>
              <div style={{ marginTop: 8, color: "#8c8c8c", fontSize: 12 }}>点任意处关闭（4 秒后自动消失）</div>
            </span>
          </div>
        </div>
      )}
      <Form form={form} layout="vertical" onFinish={onFinish} style={{ maxWidth: 720 }}>
        <Space style={{ width: "100%" }} size="middle" direction="vertical">
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
            <Form.Item
              label="Sonar 地址"
              name="sonar_url"
              initialValue={overview?.sonar_url || "http://localhost:9000"}
              rules={[{ required: true }]}
            >
              <Input />
            </Form.Item>
            <Form.Item label="Sonar 令牌" name="sonar_token">
              <Input.Password autoComplete="off" />
            </Form.Item>
          </div>
          <Form.Item label="GitLab 令牌" name="gitlab_token">
            <Input.Password autoComplete="off" />
          </Form.Item>
          <Form.Item label="大模型密钥（自备）" name="llm_token">
            <Input.Password autoComplete="off" />
          </Form.Item>
          <Form.Item label="允许修改的仓库（白名单）">
            {choices.length === 0 ? (
              <span style={{ color: "#8c8c8c" }}>填好 Sonar 后刷新，这里会列出项目</span>
            ) : (
              <Checkbox.Group
                value={selected}
                onChange={(v) => setPicked(v as string[])}
                options={choices.map((c) => ({ label: c.key, value: c.key }))}
              />
            )}
          </Form.Item>
          <Form.Item label="名单里没有的，直接填项目 key（多个用逗号分开）" name="project_keys">
            <Input placeholder="my-service" />
          </Form.Item>
          <Form.Item>
            <Button type="primary" htmlType="submit">
              保存接入
            </Button>
          </Form.Item>
          {result && (
            <Alert
              type={result.ok ? "success" : "error"}
              showIcon
              message={result.text}
              closable
              onClose={() => setResult(null)}
            />
          )}
        </Space>
      </Form>
      </Card>
    </Space>
  );
}
