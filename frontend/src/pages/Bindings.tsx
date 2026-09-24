import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Checkbox, Input, Modal, Select, Space, Table, Tag, message } from "antd";
import { api } from "../lib/api";

interface Row {
  key: string;
  sonar_key: string;
  gitlab_url: string;
  provider: string;
  health?: { ok: boolean; sonar_ok: boolean; git_ok: boolean; hint?: string };
  testing?: boolean;
  error?: string;
}

function providerOf(url: string): string {
  const u = url.toLowerCase();
  if (u.includes("github.com")) return "GitHub";
  if (u.includes("dev.azure.com") || u.includes("visualstudio.com")) return "Azure";
  if (u.includes("gitlab")) return "GitLab";
  return url ? "未知" : "—";
}

export default function BindingsTable() {
  const qc = useQueryClient();
  const [rows, setRows] = useState<Row[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [importProvider, setImportProvider] = useState("gitlab");
  const [importing, setImporting] = useState(false);
  const [candidates, setCandidates] = useState<Array<{ name: string; url: string; private: boolean }>>([]);
  const [pickedUrls, setPickedUrls] = useState<string[]>([]);
  const [importError, setImportError] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);
  const [wizardProvider, setWizardProvider] = useState("gitlab");
  const [wizardName, setWizardName] = useState("");
  const [wizardKey, setWizardKey] = useState("");
  const [creating, setCreating] = useState(false);

  const projects = useQuery({
    queryKey: ["sonar-projects"],
    queryFn: () => api.sonarProjects().catch(() => ({ projects: [] as string[] })),
  });
  const health = useQuery({
    queryKey: ["bindings-health"],
    queryFn: () => api.bindingsHealth().catch(() => ({ bindings: [] })),
  });

  const healthMap = Object.fromEntries(
    ((health.data?.bindings ?? []) as Array<{
      sonar_key: string;
      ok: boolean;
      sonar_ok?: boolean;
      git_ok?: boolean;
      hint?: string;
    }>).map((h) => [h.sonar_key, h]),
  );

  useEffect(() => {
    if (loaded) return;
    fetch("/api/bindings")
      .then((r) => r.json())
      .then((d: { bindings: Array<{ sonar_key: string; gitlab_url: string; provider: string }> }) => {
        setRows(
          (d.bindings ?? []).map((b, i) => {
            const h = healthMap[b.sonar_key];
            return {
              key: `${b.sonar_key}::${i}`,
              sonar_key: b.sonar_key,
              gitlab_url: b.gitlab_url,
              provider: b.provider || providerOf(b.gitlab_url),
              health: h
                ? { ok: !!h.ok, sonar_ok: h.sonar_ok !== false, git_ok: h.git_ok !== false, hint: h.hint }
                : undefined,
              error: h && !h.ok ? h.hint : undefined,
            };
          }),
        );
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loaded]);

  const patch = (key: string, p: Partial<Row>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...p, error: undefined } : r)));

  const testRow = (row: Row) => {
    if (!row.sonar_key || !row.gitlab_url) {
      patch(row.key, { error: "两列都填了才能测。" });
      return;
    }
    patch(row.key, { testing: true });
    api
      .bindingsTest(row.sonar_key, row.gitlab_url)
      .then((d) => {
        patch(row.key, {
          testing: false,
          provider: d.provider || providerOf(row.gitlab_url),
          health: { ok: d.ok, sonar_ok: d.sonar_ok, git_ok: d.git_ok },
          error: d.ok
            ? undefined
            : [d.sonar_ok ? "" : d.sonar_hint || "Sonar 项目不存在", d.git_ok ? "" : d.git_hint || "仓库拉不到"].filter(Boolean).join("；"),
        });
      })
      .catch((e: Error) => patch(row.key, { testing: false, error: e.message }));
  };

  const saveRow = (row: Row) => {
    if (!row.sonar_key || !row.gitlab_url) {
      patch(row.key, { error: "两列都填了才能存。" });
      return;
    }
    api
      .bindings({ sonar_key: row.sonar_key, gitlab_url: row.gitlab_url })
      .then(() => {
        message.success(`已保存 ${row.sonar_key}`);
        patch(row.key, { error: undefined });
        qc.invalidateQueries({ queryKey: ["overview"] });
        qc.invalidateQueries({ queryKey: ["bindings-health"] });
      })
      .catch((e: Error) => patch(row.key, { error: e.message }));
  };

  const removeRow = (row: Row) => {
    const drop = () => setRows((rs) => rs.filter((r) => r.key !== row.key));
    if (!row.sonar_key) {
      drop();
      return;
    }
    api
      .bindingsDelete(row.sonar_key)
      .then(() => {
        message.success(`已删除 ${row.sonar_key}`);
        drop();
        qc.invalidateQueries({ queryKey: ["overview"] });
      })
      .catch((e: Error) => patch(row.key, { error: e.message }));
  };

  const options = (projects.data?.projects ?? []).map((p) => ({ label: p, value: p }));

  return (
    <Card title="仓库绑定" extra={`${rows.length} 个`}>
      <Table<Row>
        rowKey="key"
        pagination={false}
        size="small"
        dataSource={rows}
        locale={{ emptyText: "还没有绑定，点下面加一行" }}
        columns={[
          {
            title: "Sonar 项目",
            dataIndex: "sonar_key",
            width: 220,
            render: (v: string, r) => (
              <Select
                style={{ width: "100%" }}
                showSearch
                allowClear
                placeholder="选或填项目 key"
                value={v || undefined}
                options={options}
                onChange={(val) => patch(r.key, { sonar_key: val || "" })}
                onInputKeyDown={(e) => {
                  const input = (e.target as HTMLInputElement).value;
                  if (e.key === "Enter" && input) patch(r.key, { sonar_key: input });
                }}
              />
            ),
          },
          {
            title: "仓库地址",
            dataIndex: "gitlab_url",
            render: (v: string, r) => (
              <Input
                placeholder="https://gitlab.com/xxx/yyy"
                value={v}
                onChange={(e) => patch(r.key, { gitlab_url: e.target.value, provider: providerOf(e.target.value) })}
                onBlur={() => {
                  if (r.sonar_key && r.gitlab_url) testRow({ ...r });
                }}
              />
            ),
          },
          {
            title: "平台",
            dataIndex: "provider",
            width: 90,
            render: (v: string) => <Tag>{v || "—"}</Tag>,
          },
          {
            title: "连通",
            key: "health",
            width: 120,
            render: (_, r) =>
              r.testing ? (
                <Tag color="processing">测速中</Tag>
              ) : r.health ? (
                r.health.ok ? (
                  <Tag color="success">都通</Tag>
                ) : (
                  <Space size={4}>
                    {!r.health.sonar_ok && <Tag color="error">Sonar</Tag>}
                    {!r.health.git_ok && <Tag color="error">Git</Tag>}
                  </Space>
                )
              ) : (
                <span style={{ color: "#bfbfbf" }}>未测</span>
              ),
          },
          {
            title: "操作",
            key: "op",
            width: 200,
            render: (_, r) => (
              <Space size={6}>
                <a onClick={() => testRow(r)}>测试</a>
                <a onClick={() => saveRow(r)}>保存</a>
                <a onClick={() => removeRow(r)} style={{ color: "#ff4d4f" }}>
                  删除
                </a>
              </Space>
            ),
          },
        ]}
      />
      {rows.some((r) => r.error) && (
        <div style={{ marginTop: 8, color: "#cf1322", fontSize: 12 }}>
          {rows.filter((r) => r.error).map((r) => (
            <div key={r.key}>
              {r.sonar_key || "（空行）"}：{r.error}
            </div>
          ))}
        </div>
      )}
      <Button
        style={{ marginTop: 12 }}
        onClick={() =>
          setRows((rs) => [...rs, { key: `new::${Date.now()}`, sonar_key: "", gitlab_url: "", provider: "" }])
        }
      >
        + 加一行
      </Button>
      <Button
        style={{ marginTop: 12, marginLeft: 8 }}
        onClick={() => {
          setImportOpen(true);
          setCandidates([]);
          setPickedUrls([]);
          setImportError("");
        }}
      >
        从托管平台导入
      </Button>
      <Button style={{ marginTop: 12, marginLeft: 8 }} type="dashed" onClick={() => setWizardOpen(true)}>
        新建仓库向导
      </Button>
      <Modal
        title="从托管平台导入"
        open={importOpen}
        onCancel={() => setImportOpen(false)}
        width={640}
        footer={[
          <Button key="cancel" onClick={() => setImportOpen(false)}>
            关闭
          </Button>,
          <Button
            key="bind"
            type="primary"
            disabled={pickedUrls.length === 0}
            onClick={() => {
              const jobs = candidates.filter((c) => pickedUrls.includes(c.url));
              let done = 0;
              const fail: string[] = [];
              const next = (i: number): void => {
                if (i >= jobs.length) {
                  message.success(`已绑定 ${done} 个${fail.length ? `，失败 ${fail.length} 个` : ""}`);
                  setImportOpen(false);
                  qc.invalidateQueries({ queryKey: ["overview"] });
                  setLoaded(false);
                  return;
                }
                const c = jobs[i];
                const key = c.name.split("/").pop() || c.name;
                api
                  .bindings({ sonar_key: key, gitlab_url: c.url })
                  .then(() => {
                    done += 1;
                    next(i + 1);
                  })
                  .catch(() => {
                    fail.push(key);
                    next(i + 1);
                  });
              };
              next(0);
            }}
          >
            绑定选中（{pickedUrls.length}）
          </Button>,
        ]}
      >
        <Space style={{ marginBottom: 12 }}>
          <Select value={importProvider} onChange={setImportProvider} style={{ width: 140 }} options={[{ label: "GitLab", value: "gitlab" }, { label: "GitHub", value: "github" }]} />
          <Button
            loading={importing}
            onClick={() => {
              setImporting(true);
              setImportError("");
              api
                .hostingProjects(importProvider)
                .then((d) => {
                  setCandidates(d.projects ?? []);
                  setPickedUrls([]);
                  if (!(d.projects ?? []).length) {
                    setImportError("拉到了，但是一个仓库都没有——令牌权限不足，或这个平台上确实没仓。");
                  }
                })
                .catch((e: Error) => setImportError(e.message))
                .finally(() => setImporting(false));
            }}
          >
            拉取仓库列表
          </Button>
        </Space>
        {importError && (
          <div style={{ marginBottom: 12, color: "#cf1322", fontSize: 13 }}>
            拉取失败：{importError}
            {importProvider === "github" && importError.includes("令牌") && (
              <span>——去接入配置把 GitHub 令牌填上。</span>
            )}
          </div>
        )}
        <Checkbox.Group
          value={pickedUrls}
          onChange={(v) => setPickedUrls(v as string[])}
          style={{ width: "100%" }}
        >
          <Space direction="vertical" style={{ width: "100%" }}>
            {candidates.map((c) => {
              const bound = rows.some((r) => r.gitlab_url === c.url);
              return (
                <Checkbox key={c.url} value={c.url} disabled={bound}>
                  {c.name} <span style={{ color: "#8c8c8c" }}>{c.url}</span>
                  {bound && <Tag style={{ marginLeft: 8 }}>已绑定</Tag>}
                </Checkbox>
              );
            })}
            {candidates.length === 0 && !importing && (
              <span style={{ color: "#8c8c8c" }}>点拉取，看令牌能看到哪些仓库（已绑定的自动过滤）</span>
            )}
          </Space>
        </Checkbox.Group>
      </Modal>
      <Modal
        title="新建仓库向导"
        open={wizardOpen}
        onCancel={() => setWizardOpen(false)}
        onOk={() => {
          if (!wizardName) {
            message.error("仓库名不能为空。");
            return;
          }
          setCreating(true);
          api
            .hostingCreate(wizardProvider, wizardName, wizardKey || wizardName)
            .then((d) => {
              message.success(`已建仓并绑定：${d.project.name}`);
              setWizardOpen(false);
              setWizardName("");
              setWizardKey("");
              qc.invalidateQueries({ queryKey: ["overview"] });
              setLoaded(false);
            })
            .catch((e: Error) => message.error(e.message))
            .finally(() => setCreating(false));
        }}
        okText="建仓并绑定"
        confirmLoading={creating}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <span>
            在托管平台建空仓（含 README），Sonar 项目会在第一次重扫时自动建出来，绑定立刻生效。
          </span>
          <Select value={wizardProvider} onChange={setWizardProvider} style={{ width: 140 }} options={[{ label: "GitLab", value: "gitlab" }, { label: "GitHub", value: "github" }]} />
          <Input placeholder="仓库名，如 test4" value={wizardName} onChange={(e) => setWizardName(e.target.value)} />
          <Input placeholder="Sonar 项目 key（空=跟仓库名）" value={wizardKey} onChange={(e) => setWizardKey(e.target.value)} />
        </Space>
      </Modal>
    </Card>
  );
}
