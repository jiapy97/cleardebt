import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Card, Checkbox, Form, Input, Space, message } from "antd";
import { api } from "../lib/api";
import { useOverview } from "../lib/useOverview";

export default function SetupPage() {
  const { data: overview } = useOverview();
  const qc = useQueryClient();
  const [form] = Form.useForm();
  const [picked, setPicked] = useState<string[] | null>(null);
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
    api
      .saveSetup({
        sonar_url: v.sonar_url,
        sonar_token: v.sonar_token || "",
        gitlab_token: v.gitlab_token || "",
        llm_token: v.llm_token || "",
        bindings: v.bindings || "",
        whitelist: selected,
        project_keys: v.project_keys || "",
      })
      .then(() => {
        message.success("已保存接入");
        qc.invalidateQueries({ queryKey: ["overview"] });
      })
      .catch((e: Error) => message.error(e.message));
  };

  return (
    <Card title="接入配置">
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
          <Form.Item
            label="每个仓库的托管地址（一行一个：项目key + 空格 + 仓库地址）"
            name="bindings"
            initialValue={overview?.binding_lines || ""}
          >
            <Input.TextArea rows={4} />
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
        </Space>
      </Form>
    </Card>
  );
}
