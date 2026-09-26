export interface RepoChoice {
  key: string;
  selected: boolean;
}

export interface RepairableRulesResponse {
  mode: "ai_codefix_list" | "sonar_quick_fix";
  rule_count: number;
  checked_at: string;
  rules: Array<{
    key: string;
    language: string;
    name: string;
  }>;
}

export interface Suggestion {
  fingerprint: string;
  rule: string;
  rule_name: string;
  path: string;
  line: number;
  message: string;
  message_zh: string;
  level: string;
  reason: string;
  fix_method: string;
  model_used: string;
  model_attempts: Array<{ model?: string; ok?: boolean; error?: string }>;
  checks: Array<{ name: string; ok: boolean | null; detail: string }>;
  diffs: Array<{ path: string; diff: string }>;
  diff_scope: "file" | "snippet";
  mr_url: string;
}

export interface Overview {
  configured: boolean;
  sonar_url: string;
  binding_lines: string;
  repo_choices: RepoChoice[];
  whitelist: string[];
  bindings: Array<Record<string, unknown>>;
  enabled: boolean;
  dry_run: boolean;
  retrieve: boolean;
  request_fix: boolean;
  backlog_automation: Record<string, unknown>;
  sonar_token_set: boolean;
  gitlab_token_set: boolean;
  github_token_set: boolean;
  azure_token_set: boolean;
  llm_token_set: boolean;
  sonar_token?: string;
  gitlab_token?: string;
  llm_token?: string;
}

export interface Issue {
  repo: string;
  rule: string;
  path: string;
  line?: number;
  message: string;
  message_zh?: string;
  eligible: boolean;
  suppressed?: boolean;
  is_new?: boolean;
  first_seen?: string;
  status?: { level: string; reason: string; mr_url: string; fingerprint?: string } | null;
  tier?: string;
  tier_source?: string;
  sonar_type?: string;
  sonar_severity?: string;
  sonar_impacts?: Array<{ softwareQuality?: string; severity?: string }>;
  sonar_effort?: string;
  quick_fix?: boolean;
  sonar_key?: string;
  fingerprint?: string;
  package?: string;
  to_version?: string;
}

export interface IssueSelection {
  rule: string;
  path: string;
  line?: number;
  sonar_key?: string;
  fingerprint?: string;
}

export function issueId(issue: Issue): string {
  if (issue.rule.startsWith("sca:") && issue.fingerprint) return `sca:${issue.fingerprint}`;
  if (issue.sonar_key) return `sonar:${issue.sonar_key}`;
  if (issue.fingerprint) return `sca:${issue.fingerprint}`;
  return `fallback:${issue.rule}:${issue.path}:${issue.line ?? 0}:${issue.message}`;
}

export function issueSelection(issue: Issue): IssueSelection {
  return {
    rule: issue.rule,
    path: issue.path,
    line: issue.line ?? 0,
    sonar_key: issue.sonar_key,
    fingerprint: issue.fingerprint,
  };
}

export interface AssignDecision {
  rule: string;
  path: string;
  level: string;
  fix_method?: string;
  reason: string;
  fingerprint?: string | null;
  action: string;
  web_url?: string;
}

export interface Session {
  id: number;
  created_at: string;
  source: string;
  status: string;
  repo: string;
  issue_count: number;
  details: Record<string, unknown>;
  finished_at: string;
}

async function req<T>(path: string, init?: RequestInit, timeoutMs = 30000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(path, {
      headers: { "content-type": "application/json" },
      ...init,
      signal: ctrl.signal,
    });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error((body as { detail?: string }).detail || `请求失败（${resp.status}）`);
    }
    return body as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时（30 秒），后端可能在重启，稍后重试。");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  overview: () => req<Overview>("/api/overview"),
  saveSetup: (body: Record<string, unknown>) =>
    req<{ ok: boolean }>("/api/setup", { method: "POST", body: JSON.stringify(body) }),
  controls: () => req<Record<string, unknown>>("/controls"),
  saveControls: (body: Record<string, unknown>) =>
    req<Record<string, unknown>>("/controls", { method: "POST", body: JSON.stringify(body) }),
  listIssues: (repo: string) =>
    req<{ repo: string; issues: Issue[]; scan_note: string }>("/api/issues/list", {
      method: "POST",
      body: JSON.stringify({ repo }),
    }),
  issueSnapshot: (repo: string) =>
    req<{ repo: string; issues: Issue[]; scan_note: string; suppressed_count: number }>(
      `/api/issues/snapshot?repo=${encodeURIComponent(repo)}`,
    ),
  suppress: (repo: string, rule: string, path: string, line: number) =>
    req<{ ok: boolean }>("/api/issues/suppress", {
      method: "POST",
      body: JSON.stringify({ repo, rule, path, line }),
    }),
  unsuppress: (repo: string, rule: string, path: string, line: number) =>
    req<{ ok: boolean }>("/api/issues/unsuppress", {
      method: "POST",
      body: JSON.stringify({ repo, rule, path, line }),
    }),
  scanProgress: (repo: string) =>
    req<{ repo: string; step: string; stale: boolean }>(
      `/api/scan/progress?repo=${encodeURIComponent(repo)}`,
    ),
  bindings: (body: { sonar_key: string; gitlab_url: string }) =>
    req<{ ok: boolean; sonar_key: string; read_only?: boolean }>("/api/bindings", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  bindingsDelete: (sonar_key: string) =>
    req<{ ok: boolean }>(`/api/bindings?sonar_key=${encodeURIComponent(sonar_key)}`, {
      method: "DELETE",
    }),
  bindingsTest: (sonar_key: string, gitlab_url: string) =>
    req<{
      ok: boolean;
      sonar_ok: boolean;
      git_ok: boolean;
      default_branch?: string;
      provider?: string;
      sonar_hint?: string;
      git_hint?: string;
    }>("/api/bindings/test", {
      method: "POST",
      body: JSON.stringify({ sonar_key, gitlab_url }),
    }),
  bindingsHealth: () =>
    req<{ bindings: Array<{ sonar_key: string; ok: boolean; hint?: string }> }>(
      "/api/bindings/health",
    ),
  sonarProjects: () =>
    req<{ projects: string[] }>("/api/sonar/projects"),
  hostingProjects: (provider: string) =>
    req<{ projects: Array<{ name: string; url: string; private: boolean }> }>(
      `/api/hosting/projects?provider=${encodeURIComponent(provider)}`,
    ),
  hostingCreate: (provider: string, name: string, sonar_key: string) =>
    req<{ project: { url: string; name: string }; binding: { sonar_key: string } }>(
      "/api/hosting/create",
      { method: "POST", body: JSON.stringify({ provider, name, sonar_key }) },
    ),
  rulesList: (prefix: string) =>
    req<{
      total: number;
      ai_codefix_list_enabled: boolean;
      rules: Array<{
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
      }>;
    }>(`/api/rules?prefix=${encodeURIComponent(prefix)}`),
  repairableRules: () => req<RepairableRulesResponse>("/api/repairable-rules"),
  suggestion: (fingerprint: string) => req<Suggestion>(`/api/suggestions/${encodeURIComponent(fingerprint)}`),
  rulesRefresh: () => req<{ ok: boolean; count: number }>("/api/rules/refresh", { method: "POST", body: "{}" }),
  rulePin: (rule: string, zh: string) =>
    req<{ rule: string }>("/api/rules/pin", {
      method: "POST",
      body: JSON.stringify({ rule, zh }),
    }),
  assign: (repo: string, issues: IssueSelection[]) =>
    req<{ started: boolean; already_running?: boolean; repo: string; session_id?: number }>(
      "/issues/assign",
      {
        method: "POST",
        body: JSON.stringify({ repo, issues }),
      },
    ),
  sessionDetail: (session_id: number) =>
    req<{
      id: number;
      status: string;
      repo: string;
      details: Record<string, unknown>;
    }>(`/api/sessions/${session_id}`),
  sessions: () => req<{ sessions: Session[] }>("/sessions"),
  mrIssues: (repo: string, mr_iid: number) =>
    req<{ issues: Issue[]; merge_request: { source_branch: string } }>(
      `/mrs/issues?repo=${encodeURIComponent(repo)}&mr_iid=${mr_iid}`,
    ),
  mrOffer: (repo: string, mr_iid: number) =>
    req<{ note_id: number }>("/mrs/offer", {
      method: "POST",
      body: JSON.stringify({ repo, mr_iid }),
    }),
  mrRemediate: (repo: string, mr_iid: number, issues: IssueSelection[]) =>
    req<{ session_id?: number; already_running?: boolean }>("/mrs/remediate", {
      method: "POST",
      body: JSON.stringify({ repo, mr_iid, issues }),
    }),
  latestSheet: () =>
    req<{ sheet: Record<string, unknown> | null }>("/api/reports/latest").then((d) => d.sheet),
};
