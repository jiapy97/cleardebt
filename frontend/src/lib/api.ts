export interface RepoChoice {
  key: string;
  selected: boolean;
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
  status?: { level: string; reason: string; mr_url: string } | null;
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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...init,
  });
  const body = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error((body as { detail?: string }).detail || `请求失败（${resp.status}）`);
  }
  return body as T;
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
  assign: (repo: string, issues: Array<{ rule: string; path: string }>) =>
    req<{ session_id: number; decisions: Array<{ action: string }> }>("/issues/assign", {
      method: "POST",
      body: JSON.stringify({ repo, issues }),
    }),
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
  mrRemediate: (repo: string, mr_iid: number, issues: Array<{ rule: string; path: string }>) =>
    req<{ session_id: number }>("/mrs/remediate", {
      method: "POST",
      body: JSON.stringify({ repo, mr_iid, issues }),
    }),
  latestSheet: () =>
    req<{ sheet: Record<string, unknown> | null }>("/api/reports/latest").then((d) => d.sheet),
  revealTokens: () =>
    req<Record<string, string>>("/api/tokens/reveal", { method: "POST", body: "{}" }),
};
