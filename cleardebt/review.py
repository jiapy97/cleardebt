"""One page: connection, switches, the settlement sheet, and suggestions.

Styles are Tailwind, built into cleardebt/static/app.css so the page does not
need a public stylesheet host.
"""

from __future__ import annotations

from html import escape

_ACTIONS = {
    "already": "已经开过请求",
    "opened": "这一轮开了请求",
    "held": "留下次再开",
    "no_mr": "不开请求",
    "dry_run": "空跑，不开请求",
    "open": "准备开请求",
}

_LEVEL_CLASS = {
    "L1": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "L2": "bg-amber-50 text-amber-800 ring-amber-200",
    "L3": "bg-rose-50 text-rose-800 ring-rose-200",
    "skip": "bg-zinc-100 text-zinc-700 ring-zinc-200",
}

_ACTION_CLASS = {
    "already": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "opened": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "held": "bg-amber-50 text-amber-800 ring-amber-200",
    "no_mr": "bg-zinc-100 text-zinc-700 ring-zinc-200",
    "dry_run": "bg-sky-50 text-sky-800 ring-sky-200",
    "open": "bg-sky-50 text-sky-800 ring-sky-200",
}


def render_page(
    sheet: dict | None,
    settings: dict | None = None,
    error: str = "",
    *,
    issues: list[dict] | None = None,
    sessions: list[dict] | None = None,
    assign_repo: str = "",
    assign_notice: str = "",
) -> str:
    settings = settings or {}
    notice = (
        f"<p class='rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-rose-200'>{escape(error)}</p>"
        if error
        else ""
    )
    state = "已接入" if settings.get("configured") else "还没填写，服务碰不到任何仓库"
    state_class = (
        "bg-emerald-50 text-emerald-800 ring-emerald-200"
        if settings.get("configured")
        else "bg-amber-50 text-amber-800 ring-amber-200"
    )
    enabled = "checked" if settings.get("enabled") else ""
    dry_run = "checked" if settings.get("dry_run") else ""
    retrieve = "checked" if settings.get("retrieve") else ""
    request_fix = "checked" if settings.get("request_fix", True) else ""
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClearDebt</title>
<link rel="stylesheet" href="/static/app.css?v=5">
<style>
.toggle-row {{ display:flex; width:100%; box-sizing:border-box; align-items:center; gap:0.75rem; padding:0.75rem 1rem; }}
.toggle-control {{ position:relative; flex:0 0 2.75rem; width:2.75rem; height:1.5rem; }}
.toggle-input {{ position:absolute; opacity:0; width:100%; height:100%; margin:0; cursor:pointer; }}
.toggle-track {{ display:block; width:2.75rem; height:1.5rem; border-radius:999px; background:#d4d4d8; }}
.toggle-knob {{ position:absolute; left:0.125rem; top:0.125rem; width:1.25rem; height:1.25rem; border-radius:999px; background:#fff; box-shadow:0 1px 2px rgb(0 0 0 / 0.2); }}
.toggle-input:checked + .toggle-track {{ background:#18181b; }}
.toggle-input:checked + .toggle-track + .toggle-knob {{ transform:translateX(1.25rem); }}
button.is-loading {{ opacity:.7; cursor:wait; }}
button.is-loading .spinner {{ display:inline-block; width:.9em; height:.9em; margin-right:.45em; border-radius:999px; border:2px solid rgb(255 255 255 / .35); border-top-color:#fff; vertical-align:-0.15em; animation:cdspin .7s linear infinite; }}
button.is-loading.bg-white .spinner {{ border-color:rgb(0 0 0 / .2); border-top-color:#18181b; }}
@keyframes cdspin {{ to {{ transform:rotate(360deg); }} }}
#toast {{ position:fixed; left:50%; bottom:1.5rem; transform:translateX(-50%) translateY(1rem); z-index:50; max-width:min(90vw,32rem); border-radius:.75rem; background:#18181b; color:#fff; font-size:.875rem; padding:.65rem 1rem; opacity:0; pointer-events:none; transition:opacity .2s, transform .2s; }}
#toast.show {{ opacity:1; transform:translateX(-50%) translateY(0); }}
#toast.error {{ background:#9f1239; }}
</style>
</head>
<body class="min-h-screen bg-zinc-100 text-zinc-900 antialiased">
<div class="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
<header class="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
<div>
<p class="text-xs font-medium uppercase tracking-[0.18em] text-zinc-500">ClearDebt</p>
<h1 class="mt-1 text-3xl font-semibold tracking-tight">质量债审核</h1>
<p class="mt-2 max-w-xl text-sm text-zinc-500">这里只看结果和开关，不改代码。</p>
</div>
<span class="inline-flex items-center rounded-full px-3 py-1 text-sm ring-1 {state_class}">{escape(state)}</span>
</header>
<div class="grid gap-6 lg:grid-cols-2">
<section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-zinc-200">
<h2 class="text-lg font-semibold tracking-tight">开关</h2>
<p class="mt-1 text-sm text-zinc-500">这几项马上生效，下一轮才会照着做。</p>
<form method="post" action="/switches" class="mt-5 space-y-4">
{_toggle("enabled", enabled, "总开关", "关掉之后，到点的那一轮不会开始。")}
{_toggle("dry_run", dry_run, "空跑", "打开之后，只出清算单，不开合并请求。")}
{_toggle("retrieve", retrieve, "检索旧例子", "打开之后，所有 LLM 可修规则会带上以前同规则的 L1 补丁片段。关掉也能跑，只是提示词里没有。")}
{_toggle("request_fix", request_fix, "请求修复", "关掉之后，不对质量门失败的合并请求开修复请求；定时与指派清 backlog 仍可跑。")}
<button type="submit" class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">保存开关</button>
</form>
{_schedule_section(settings)}
{_project_switches_section(settings)}
</section>
<section class="rounded-2xl bg-white p-6 shadow-sm ring-1 ring-zinc-200">
<h2 class="text-lg font-semibold tracking-tight">接入</h2>
<p class="mt-1 text-sm text-zinc-500">地址、令牌和允许修改的仓库。</p>
{notice}
<form method="post" action="/setup" class="mt-5 grid gap-4 sm:grid-cols-2">
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="sonar_url">Sonar 地址</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="sonar_url" type="text" name="sonar_url" value="{escape(settings.get('sonar_url') or 'http://localhost:9000')}" required>
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="sonar_token">Sonar 令牌</label>
{_secret_input("sonar_token", settings, required=True)}
</div>
<div class="sm:col-span-2">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="gitlab_token">GitLab 令牌</label>
{_secret_input("gitlab_token", settings)}
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="github_token">GitHub 令牌</label>
{_secret_input("github_token", settings)}
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="azure_token">Azure DevOps 令牌</label>
{_secret_input("azure_token", settings)}
</div>
<div class="sm:col-span-2">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="llm_token">大模型密钥（自备）</label>
{_secret_input("llm_token", settings, hint="环境变量 CLEARDEBT_LLM_API_KEY 优先；留空则保留已保存的密钥。")}
</div>
<div class="sm:col-span-2">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="bindings">每个仓库的托管地址</label>
<textarea class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="bindings" name="bindings" rows="5" placeholder="my-service https://gitlab.com/组/项目&#10;other https://github.com/org/repo&#10;ado https://dev.azure.com/org/project/_git/repo">{escape(settings.get('binding_lines') or '')}</textarea>
<p class="mt-2 text-sm text-zinc-500">一行一个。先写 Sonar 项目 key，空一格，再写 GitLab / GitHub / Azure DevOps 仓库地址。按地址自动识别平台；填上对应令牌。没写地址的会跳过。</p>
</div>
<div class="sm:col-span-2">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="whitelist">允许修改的仓库（白名单）</label>
<select class="h-36 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="whitelist" name="whitelist" multiple>
{_repo_options(settings.get('repo_choices') or [])}
</select>
<p class="mt-2 text-sm text-zinc-500">名单里没有的，可以直接填项目 key，多个用逗号分开。</p>
<input class="mt-2 w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="project_keys" type="text" name="project_keys" placeholder="my-service">
</div>
<div class="sm:col-span-2">
<button type="submit" class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">保存接入</button>
</div>
</form>
</section>
</div>
{_assign_section(settings, issues, assign_repo, assign_notice)}
{_request_fix_section(settings)}
{_activity_section(sessions)}
<section class="mt-6 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-zinc-200">
<div class="mb-4 flex flex-wrap items-end justify-between gap-3">
<h2 class="text-lg font-semibold tracking-tight">清算单</h2>
</div>
{_sheet_intro(sheet)}
{_mobile_sheet(sheet)}
<div class="mt-4 hidden overflow-x-auto md:block">
<table class="w-full min-w-[56rem] border-separate border-spacing-0 text-left text-sm">
<thead>
<tr class="text-xs uppercase tracking-wide text-zinc-500">
<th class="border-b border-zinc-200 px-3 py-2 font-medium">规则</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">文件</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">级别</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">这一轮</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">说明</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">建议片段</th>
</tr>
</thead>
<tbody>
{_sheet_rows(sheet)}
</tbody>
</table>
</div>
</section>
</div>
<div id="toast" role="status"></div>
<script>
(function () {{
  var toastEl = document.getElementById("toast");
  var toastTimer = null;
  function toast(text, isError) {{
    if (!toastEl) return;
    toastEl.textContent = text;
    toastEl.className = isError ? "error show" : "show";
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () {{ toastEl.className = isError ? "error" : ""; }}, 4000);
  }}
  function setLoading(btn, on, label) {{
    if (!btn) return;
    if (on) {{
      if (btn.disabled) return;
      btn.dataset.orig = btn.innerHTML;
      btn.disabled = true;
      btn.classList.add("is-loading");
      btn.innerHTML = '<span class="spinner"></span>' + (label || "正在处理…");
    }} else {{
      btn.disabled = false;
      btn.classList.remove("is-loading");
      if (btn.dataset.orig) btn.innerHTML = btn.dataset.orig;
    }}
  }}
  // 所有整页表单改成异步提交：按钮只转圈，不刷新整页。
  document.addEventListener("submit", function (e) {{
    var form = e.target;
    if (!form || form.tagName !== "FORM") return;
    if ((form.method || "get").toLowerCase() !== "post") return;
    e.preventDefault();
    var btn = e.submitter || form.querySelector('button[type="submit"]');
    setLoading(btn, true);
    var y = window.scrollY;
    fetch(form.action, {{ method: "POST", body: new FormData(form), redirect: "follow", headers: {{ "x-requested-with": "fetch" }} }})
      .then(function (resp) {{ return resp.text().then(function (text) {{ return {{ ok: resp.ok, text: text }}; }}); }})
      .then(function (result) {{
        if (result.text.indexOf("<html") !== -1 || result.text.indexOf("<!DOCTYPE") !== -1) {{
          document.open();
          document.write(result.text);
          document.close();
          requestAnimationFrame(function () {{ window.scrollTo(0, y); }});
        }} else if (result.ok) {{
          setLoading(btn, false);
          toast("已保存");
        }} else {{
          setLoading(btn, false);
          toast(result.text.slice(0, 200) || "请求失败，请重试", true);
        }}
      }})
      .catch(function () {{
        setLoading(btn, false);
        toast("请求失败，请检查服务后重试", true);
      }});
  }}, true);
  // 请求修复区的三个按钮：点后转圈，状态文案变化时恢复。
  var mrIds = ["mr_list_btn", "mr_offer_btn", "mr_run_btn"];
  document.addEventListener("click", function (e) {{
    var b = e.target && e.target.closest ? e.target.closest("button") : null;
    if (!b || mrIds.indexOf(b.id) === -1) return;
    var labels = {{ mr_list_btn: "正在列出…", mr_offer_btn: "正在留言…", mr_run_btn: "正在运行…" }};
    setLoading(b, true, labels[b.id]);
  }}, true);
  var mrStatus = document.getElementById("mr_status");
  if (mrStatus && window.MutationObserver) {{
    new MutationObserver(function () {{
      mrIds.forEach(function (id) {{
        var b = document.getElementById(id);
        if (b && b.disabled) setLoading(b, false);
      }});
    }}).observe(mrStatus, {{ childList: true, characterData: true, subtree: true }});
  }}
}})();
</script>
</body>
</html>
"""


def _assign_section(settings: dict, issues: list[dict] | None, assign_repo: str, notice: str = "") -> str:
    choices = settings.get("repo_choices") or []
    repo = assign_repo or next((item["key"] for item in choices if item.get("selected")), "")
    options = _repo_options(
        [{"key": item.get("key"), "selected": item.get("key") == repo} for item in choices]
        if choices
        else ([{"key": repo, "selected": True}] if repo else [])
    )
    rows = _issue_rows(issues)
    done = (
        f"<p class='mt-5 rounded-xl bg-emerald-50 px-4 py-3 text-sm text-emerald-800 ring-1 ring-emerald-200'>{escape(notice)}</p>"
        if notice
        else ""
    )
    return f"""<section class="mt-6 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-zinc-200">
<h2 class="text-lg font-semibold tracking-tight">指派给 Agent</h2>
<p class="mt-1 text-sm text-zinc-500">勾选主分支上的可修告警，不必等定时。不可修的会跳过并提示。每次列出都是 Sonar 最新告警，并带上我们账本里的最新状态。</p>
{done}
<form method="post" action="/issues/list" class="mt-5 flex flex-wrap items-end gap-3">
<div class="min-w-[12rem] flex-1">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="assign_repo">项目</label>
<select class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="assign_repo" name="repo" required>
{options or '<option value="" disabled selected>先在接入里选仓库</option>'}
</select>
</div>
<button type="submit" class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">列出告警</button>
</form>
<form method="post" action="/issues/assign-form" class="mt-4">
<input type="hidden" name="repo" value="{escape(repo)}">
<div class="overflow-x-auto">
<table class="w-full min-w-[40rem] border-separate border-spacing-0 text-left text-sm">
<thead>
<tr class="text-xs uppercase tracking-wide text-zinc-500">
<th class="border-b border-zinc-200 px-3 py-2 font-medium">选</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">规则</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">文件</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">行</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">说明</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">可修</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">最新状态</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<button type="submit" class="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">指派给 Agent</button>
</form>
</section>"""


def _line_cell(line: object) -> str:
    try:
        number = int(line or 0)
    except (TypeError, ValueError):
        number = 0
    return f"L{number}" if number > 0 else "—"


def _issue_rows(issues: list[dict] | None) -> str:
    if issues is None:
        return "<tr><td class='px-3 py-6 text-sm text-zinc-500' colspan='7'>选好项目后点「列出告警」。</td></tr>"
    if not issues:
        return "<tr><td class='px-3 py-6 text-sm text-zinc-500' colspan='7'>这个项目没有打开的告警。</td></tr>"
    lines = []
    for item in issues:
        eligible = bool(item.get("eligible"))
        value = escape(f"{item.get('rule') or ''}|{item.get('path') or ''}")
        box = (
            f'<input type="checkbox" name="selected" value="{value}">'
            if eligible
            else '<input type="checkbox" disabled>'
        )
        mark = "可修" if eligible else "跳过"
        mark_class = (
            "bg-emerald-50 text-emerald-800 ring-emerald-200"
            if eligible
            else "bg-zinc-100 text-zinc-600 ring-zinc-200"
        )
        lines.append(
            "<tr class='align-top hover:bg-zinc-50'>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{box}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3 font-medium'>{escape(str(item.get('rule') or ''))}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3 text-zinc-600'>{escape(str(item.get('path') or '—'))}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3 text-zinc-600 whitespace-nowrap'>{_line_cell(item.get('line'))}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3 text-zinc-700'><span class='block max-w-64 truncate' title='{escape(str(item.get('message') or ''))}'>{escape(str(item.get('message') or '—'))}</span></td>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>"
            f"<span class='inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 {mark_class}'>{mark}</span>"
            "</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{_status_cell(item.get('status'))}</td>"
            "</tr>"
        )
    return "".join(lines)


def _status_cell(status: dict | None) -> str:
    if not status:
        return (
            "<span class='inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 "
            "bg-zinc-100 text-zinc-600 ring-zinc-200'>待处理</span>"
        )
    if status.get("mr_url"):
        url = escape(str(status["mr_url"]))
        return (
            "<span class='inline-flex flex-wrap items-center gap-x-2 gap-y-1'>"
            "<span class='inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 "
            "bg-emerald-50 text-emerald-800 ring-emerald-200'>已开请求</span>"
            f'<a class="whitespace-nowrap text-sky-700 underline-offset-2 hover:underline" href="{url}">查看请求</a>'
            "</span>"
        )
    level = (status.get("level") or "").strip()
    reason = escape(str(status.get("reason") or ""))
    label = {"L1": "修好了", "L2": "要人工改", "L3": "没修成", "skip": "不修"}.get(level, level or "已跑过")
    classes = _LEVEL_CLASS.get(level, "bg-zinc-100 text-zinc-700 ring-zinc-200")
    return (
        "<span class='inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 "
        f"{classes}' title='{reason}'>{escape(label)}</span>"
    )


def _activity_section(sessions: list[dict] | None) -> str:
    rows = _session_rows(sessions)
    return f"""<section class="mt-6 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-zinc-200">
<h2 class="text-lg font-semibold tracking-tight">Agent 活动</h2>
<p class="mt-1 text-sm text-zinc-500">最近会话：排队、运行、完成；能区分手动指派和定时跑。</p>
<div class="mt-4 overflow-x-auto">
<table class="w-full min-w-[40rem] border-separate border-spacing-0 text-left text-sm">
<thead>
<tr class="text-xs uppercase tracking-wide text-zinc-500">
<th class="border-b border-zinc-200 px-3 py-2 font-medium">时间</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">来源</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">项目</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">条数</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">状态</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">说明</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
</div>
</section>"""


def _request_fix_section(settings: dict) -> str:
    choices = settings.get("repo_choices") or []
    options = _repo_options(choices) or '<option value="" disabled selected>先在接入里选仓库</option>'
    return f"""<section class="mt-6 rounded-2xl bg-white p-6 shadow-sm ring-1 ring-zinc-200">
<h2 class="text-lg font-semibold tracking-tight">请求修复</h2>
<p class="mt-1 text-sm text-zinc-500">质量门失败的合并请求：在请求下留言，或勾选后开出打向<strong>原源分支</strong>的修复请求（不会硬推）。</p>
<div class="mt-5 grid gap-4 sm:grid-cols-[1fr_8rem_auto]">
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="mr_repo">项目</label>
<select class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="mr_repo">{options}</select>
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="mr_iid">合并/拉取请求号</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="mr_iid" type="number" min="1" placeholder="GitLab / GitHub / Azure 请求号">
</div>
<div class="flex flex-wrap items-end gap-2">
<button type="button" id="mr_list_btn" class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">列出告警</button>
<button type="button" id="mr_offer_btn" class="rounded-lg bg-white px-4 py-2 text-sm font-medium text-zinc-900 ring-1 ring-zinc-300 hover:bg-zinc-50">在请求下留言</button>
</div>
</div>
<p id="mr_status" class="mt-3 text-sm text-zinc-500"></p>
<div class="mt-4 overflow-x-auto">
<table class="w-full min-w-[40rem] border-separate border-spacing-0 text-left text-sm">
<thead>
<tr class="text-xs uppercase tracking-wide text-zinc-500">
<th class="border-b border-zinc-200 px-3 py-2 font-medium">选</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">规则</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">文件</th>
<th class="border-b border-zinc-200 px-3 py-2 font-medium">可修</th>
</tr>
</thead>
<tbody id="mr_issue_rows">
<tr><td class="px-3 py-6 text-sm text-zinc-500" colspan="4">填好项目和合并请求号后点「列出告警」。</td></tr>
</tbody>
</table>
</div>
<button type="button" id="mr_run_btn" class="mt-4 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">运行修复 Agent</button>
<script>
(function () {{
  const status = document.getElementById("mr_status");
  const rows = document.getElementById("mr_issue_rows");
  function repo() {{ return document.getElementById("mr_repo").value; }}
  function iid() {{ return Number(document.getElementById("mr_iid").value || 0); }}
  function setStatus(text, ok) {{
    status.textContent = text || "";
    status.className = "mt-3 text-sm " + (ok === false ? "text-rose-700" : "text-zinc-500");
  }}
  function renderIssues(issues) {{
    if (!issues || !issues.length) {{
      rows.innerHTML = '<tr><td class="px-3 py-6 text-sm text-zinc-500" colspan="4">这条请求没有打开的告警。</td></tr>';
      return;
    }}
    rows.innerHTML = issues.map(function (item) {{
      const value = encodeURIComponent(item.rule + "|" + item.path);
      const box = item.eligible
        ? '<input type="checkbox" class="mr-pick" data-rule="' + item.rule + '" data-path="' + item.path + '">'
        : '<input type="checkbox" disabled>';
      const mark = item.eligible ? "可修" : "跳过";
      return '<tr class="align-top hover:bg-zinc-50"><td class="border-b border-zinc-100 px-3 py-3">' + box +
        '</td><td class="border-b border-zinc-100 px-3 py-3 font-medium">' + item.rule +
        '</td><td class="border-b border-zinc-100 px-3 py-3 text-zinc-600">' + item.path +
        '</td><td class="border-b border-zinc-100 px-3 py-3">' + mark + '</td></tr>';
    }}).join("");
  }}
  document.getElementById("mr_list_btn").addEventListener("click", async function () {{
    setStatus("正在列出…");
    const response = await fetch("/mrs/issues?repo=" + encodeURIComponent(repo()) + "&mr_iid=" + iid());
    const body = await response.json().catch(function () {{ return {{}}; }});
    if (!response.ok) {{
      setStatus(body.detail || "列不出告警。", false);
      return;
    }}
    const source = (body.merge_request && body.merge_request.source_branch) || "";
    setStatus("源分支 " + source + "；告警 " + (body.issues || []).length + " 条。修复请求会打向该源分支。");
    renderIssues(body.issues || []);
  }});
  document.getElementById("mr_offer_btn").addEventListener("click", async function () {{
    setStatus("正在留言…");
    const response = await fetch("/mrs/offer", {{
      method: "POST",
      headers: {{ "content-type": "application/json" }},
      body: JSON.stringify({{ repo: repo(), mr_iid: iid() }}),
    }});
    const body = await response.json().catch(function () {{ return {{}}; }});
    if (!response.ok) {{
      setStatus(body.detail || "留言失败。", false);
      return;
    }}
    setStatus("已在合并请求下留言（note " + body.note_id + "）。");
  }});
  document.getElementById("mr_run_btn").addEventListener("click", async function () {{
    const picks = Array.from(document.querySelectorAll(".mr-pick:checked")).map(function (el) {{
      return {{ rule: el.getAttribute("data-rule"), path: el.getAttribute("data-path") }};
    }});
    if (!picks.length) {{
      setStatus("先勾选可修告警。", false);
      return;
    }}
    setStatus("正在运行修复 Agent…");
    const response = await fetch("/mrs/remediate", {{
      method: "POST",
      headers: {{ "content-type": "application/json" }},
      body: JSON.stringify({{ repo: repo(), mr_iid: iid(), issues: picks }}),
    }});
    const body = await response.json().catch(function () {{ return {{}}; }});
    if (!response.ok) {{
      setStatus(body.detail || "没有跑完。", false);
      return;
    }}
    setStatus("完成。会话 #" + body.session_id + "；决策 " + (body.decisions || []).length + " 条。刷新页面可看 Agent 活动。");
  }});
}})();
</script>
</section>"""


_SOURCE_LABEL = {"manual": "手动指派", "scheduled": "定时", "request_fix": "请求修复"}
_STATUS_LABEL = {
    "pending": "排队",
    "running": "运行",
    "completed": "完成",
    "failed": "失败",
}


def _session_rows(sessions: list[dict] | None) -> str:
    if not sessions:
        return "<tr><td class='px-3 py-6 text-sm text-zinc-500' colspan='6'>还没有会话。</td></tr>"
    lines = []
    for item in sessions:
        source = _SOURCE_LABEL.get(item.get("source") or "", item.get("source") or "—")
        status = _STATUS_LABEL.get(item.get("status") or "", item.get("status") or "—")
        details = item.get("details") or {}
        note = details.get("warning") or details.get("error") or ""
        if not note and item.get("finished_at"):
            note = f"结束于 {item['finished_at']}"
        lines.append(
            "<tr class='align-top hover:bg-zinc-50'>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{escape(str(item.get('created_at') or '—'))}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{escape(source)}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{escape(str(item.get('repo') or '—'))}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{escape(str(item.get('issue_count') or 0))}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3'>{escape(status)}</td>"
            f"<td class='border-b border-zinc-100 px-3 py-3 text-zinc-600'>{escape(note or '—')}</td>"
            "</tr>"
        )
    return "".join(lines)


def _schedule_section(settings: dict) -> str:
    from cleardebt.schedule import normalize_automation

    auto = normalize_automation(settings.get("backlog_automation") or {})
    enabled = "checked" if auto.get("enabled") else ""
    freq = auto.get("frequency") or "daily"
    daily_sel = "selected" if freq == "daily" else ""
    weekly_sel = "selected" if freq == "weekly" else ""
    weekday = int(auto.get("weekday") or 0)
    pause = auto.get("pause_when_open_mrs")
    pause_value = "" if pause is None else str(pause)
    weekday_options = []
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for index, label in enumerate(labels):
        selected = "selected" if index == weekday else ""
        weekday_options.append(f'<option value="{index}" {selected}>{label}</option>')
    return f"""<form method="post" action="/schedule" class="mt-6 space-y-3 border-t border-zinc-100 pt-5">
<h3 class="text-sm font-semibold tracking-tight">定时清 backlog</h3>
<p class="text-sm text-zinc-500">工人每小时整点检查一次是否到点。绑定里若带有 automation，可覆盖该项目的全局日程。</p>
<label class="toggle-row rounded-xl bg-zinc-50 ring-1 ring-zinc-200">
<span class="toggle-control">
<input class="toggle-input" type="checkbox" name="schedule_enabled" value="true" {enabled}>
<span class="toggle-track"></span>
<span class="toggle-knob"></span>
</span>
<span>
<span class="block text-sm font-medium">打开自动清 backlog</span>
<span class="mt-0.5 block text-sm text-zinc-500">关掉后定时工人跳过；手动指派不受影响。</span>
</span>
</label>
<div class="grid gap-3 sm:grid-cols-2">
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="frequency">频率</label>
<select class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="frequency" name="frequency">
<option value="daily" {daily_sel}>每天</option>
<option value="weekly" {weekly_sel}>每周</option>
</select>
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="weekday">星期（仅每周）</label>
<select class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="weekday" name="weekday">
{''.join(weekday_options)}
</select>
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="hour">时（0–23）</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="hour" type="number" name="hour" min="0" max="23" value="{int(auto.get('hour') or 8)}">
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="minute">分（0–59）</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="minute" type="number" name="minute" min="0" max="59" value="{int(auto.get('minute') or 0)}">
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="timezone">时区</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="timezone" type="text" name="timezone" value="{escape(str(auto.get('timezone') or 'Asia/Shanghai'))}">
</div>
<div>
<label class="mb-1 block text-sm font-medium text-zinc-700" for="pause_when_open_mrs">打开请求过多则暂停</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm" id="pause_when_open_mrs" type="number" name="pause_when_open_mrs" min="1" placeholder="空=不限制" value="{escape(pause_value)}">
</div>
</div>
<button type="submit" class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">保存日程</button>
</form>"""


def _project_switches_section(settings: dict) -> str:
    from cleardebt.schedule import normalize_automation

    bindings = settings.get("bindings") or []
    whitelist = settings.get("whitelist") or [
        item.get("sonar_key") for item in bindings if item.get("sonar_key")
    ]
    # Prefer whitelist order; fall back to binding keys.
    names = []
    for key in [*whitelist, *[item.get("sonar_key") for item in bindings]]:
        if key and key not in names:
            names.append(key)
    if not names:
        return (
            "<p class='mt-5 text-sm text-zinc-500'>白名单有项目后，可在这里按项目开关 "
            "backlog 修复、请求修复，以及覆盖全局日程。</p>"
        )
    by_key = {item.get("sonar_key"): item for item in bindings}
    rows = []
    for key in names:
        item = by_key.get(key) or {}
        backlog = "checked" if item.get("backlog_fix", True) else ""
        request = "checked" if item.get("request_fix", True) else ""
        auto = item.get("automation") or {}
        override = "checked" if auto else ""
        sched = "checked" if (not auto or auto.get("enabled", True)) else ""
        if auto:
            normalized = normalize_automation(auto)
            sched = "checked" if normalized.get("enabled") else ""
            pause = normalized.get("pause_when_open_mrs")
            pause_value = "" if pause is None else str(pause)
        else:
            pause_value = ""
        rows.append(
            "<tr class='align-middle'>"
            f"<td class='border-b border-zinc-100 px-2 py-2 font-medium'>{escape(key)}"
            f'<input type="hidden" name="project" value="{escape(key)}"></td>'
            f'<td class="border-b border-zinc-100 px-2 py-2 text-center">'
            f'<input type="checkbox" name="backlog_fix" value="{escape(key)}" {backlog}></td>'
            f'<td class="border-b border-zinc-100 px-2 py-2 text-center">'
            f'<input type="checkbox" name="request_fix" value="{escape(key)}" {request}></td>'
            f'<td class="border-b border-zinc-100 px-2 py-2 text-center">'
            f'<input type="checkbox" name="schedule_override" value="{escape(key)}" {override}></td>'
            f'<td class="border-b border-zinc-100 px-2 py-2 text-center">'
            f'<input type="checkbox" name="schedule_enabled" value="{escape(key)}" {sched}></td>'
            f'<td class="border-b border-zinc-100 px-2 py-2 text-center">'
            f'<input type="hidden" name="pause_project" value="{escape(key)}">'
            f'<input class="w-20 rounded border border-zinc-300 px-1 py-1 text-center text-sm" '
            f'type="number" min="1" name="pause_value" value="{escape(pause_value)}" '
            f'placeholder="—"></td>'
            "</tr>"
        )
    return f"""<form method="post" action="/project-switches" class="mt-6">
<h3 class="text-sm font-semibold tracking-tight">按项目开关</h3>
<p class="mt-1 text-sm text-zinc-500">每个仓库可单独开/关 backlog（定时与指派）和请求修复。勾选「覆盖日程」后，用「定时开」和「暂停上限」覆盖全局日程；合入仍须人在托管平台点头。</p>
<table class="mt-3 w-full text-left text-sm">
<thead>
<tr class="text-xs uppercase tracking-wide text-zinc-500">
<th class="border-b border-zinc-200 px-2 py-2 font-medium">项目</th>
<th class="border-b border-zinc-200 px-2 py-2 font-medium text-center">Backlog</th>
<th class="border-b border-zinc-200 px-2 py-2 font-medium text-center">请求修复</th>
<th class="border-b border-zinc-200 px-2 py-2 font-medium text-center">覆盖日程</th>
<th class="border-b border-zinc-200 px-2 py-2 font-medium text-center">定时开</th>
<th class="border-b border-zinc-200 px-2 py-2 font-medium text-center">暂停上限</th>
</tr>
</thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<button type="submit" class="mt-3 rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">保存项目开关</button>
</form>"""


def _secret_input(name: str, settings: dict, *, required: bool = False, hint: str = "") -> str:
    saved = bool(settings.get(f"{name}_set"))
    placeholder = "已保存，留空则不变" if saved else ""
    need = " required" if required and not saved else ""
    note = ""
    if hint:
        note = f'<p class="mt-2 text-sm text-zinc-500">{escape(hint)}</p>'
    elif saved:
        note = '<p class="mt-2 text-sm text-zinc-500">已保存；留空再保存不会改掉。</p>'
    return (
        f'<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none '
        f'ring-zinc-900 focus:ring-2" id="{escape(name)}" type="password" name="{escape(name)}" '
        f'value="" autocomplete="off" placeholder="{escape(placeholder)}"{need}>'
        f"{note}"
    )


def _toggle(name: str, checked: str, title: str, detail: str) -> str:
    return f"""<label class="toggle-row rounded-xl bg-zinc-50 ring-1 ring-zinc-200">
<span class="min-w-0 flex-1">
<span class="block text-sm font-medium">{escape(title)}</span>
<span class="mt-0.5 block text-sm text-zinc-500">{escape(detail)}</span>
</span>
<span class="toggle-control">
<input class="toggle-input" type="checkbox" name="{name}" value="true" {checked}>
<span class="toggle-track"></span>
<span class="toggle-knob"></span>
</span>
</label>"""


def _sheet_intro(sheet: dict | None) -> str:
    if not sheet:
        return "<p class='text-sm text-zinc-500'>还没有跑过一轮。</p>"
    kind = "这一轮是空跑，没有开合并请求。" if sheet.get("dry_run") else "这一轮不是空跑。"
    return (
        "<p class='text-sm text-zinc-500'>"
        f"最近一轮：{escape(str(sheet.get('repo') or ''))}，{escape(str(sheet.get('created_at') or ''))}。{kind}"
        "</p>"
    )


def _mobile_sheet(sheet: dict | None) -> str:
    decisions = (sheet or {}).get("decisions") or []
    if not decisions:
        return "<p class='mt-4 text-sm text-zinc-500 md:hidden'>还没有清算记录。</p>"
    cards = "".join(_mobile_card(item) for item in decisions)
    return f"<div class='mt-4 space-y-3 md:hidden'>{cards}</div>"


def _mobile_card(item: dict) -> str:
    action = item.get("action") or ""
    path = escape(str(item.get("path") or "—"))
    return (
        "<article class='rounded-xl bg-zinc-50 p-4 ring-1 ring-zinc-200'>"
        "<div class='flex flex-wrap items-center gap-2'>"
        f"<span class='font-medium'>{escape(str(item.get('rule') or ''))}</span>"
        f"{_pill(item.get('level'), _LEVEL_CLASS)}"
        f"{_pill(_ACTIONS.get(action, action), _ACTION_CLASS, action)}"
        "</div>"
        f"<p class='mt-2 text-sm text-zinc-500'>{path}</p>"
        f"<div class='mt-2 text-sm text-zinc-700'>{_detail(item)}</div>"
        + (
            f"<div class='mt-3'>{_suggestion(item['suggestion'])}</div>"
            if item.get("suggestion")
            else ""
        )
        + "</article>"
    )


def _sheet_rows(sheet: dict | None) -> str:
    decisions = (sheet or {}).get("decisions") or []
    if not decisions:
        return "<tr><td class='px-3 py-6 text-sm text-zinc-500' colspan='6'>还没有清算记录。</td></tr>"
    return "".join(_decision(item) for item in decisions)


def _decision(item: dict) -> str:
    action = item.get("action") or ""
    label = _ACTIONS.get(action, action)
    return (
        "<tr class='align-top hover:bg-zinc-50'>"
        f"<td class='border-b border-zinc-100 px-3 py-3 font-medium'>{escape(str(item.get('rule') or ''))}</td>"
        f"<td class='border-b border-zinc-100 px-3 py-3 text-zinc-600'>{escape(str(item.get('path') or '—'))}</td>"
        f"<td class='border-b border-zinc-100 px-3 py-3'>{_pill(item.get('level'), _LEVEL_CLASS)}</td>"
        f"<td class='border-b border-zinc-100 px-3 py-3'>{_pill(label, _ACTION_CLASS, action)}</td>"
        f"<td class='border-b border-zinc-100 px-3 py-3 text-zinc-700'>{_detail(item)}</td>"
        f"<td class='border-b border-zinc-100 px-3 py-3'>{_suggestion(item.get('suggestion'))}</td>"
        "</tr>"
    )


def _pill(text, styles: dict[str, str], key: str | None = None) -> str:
    if not text:
        return "—"
    classes = styles.get(key if key is not None else text, "bg-zinc-100 text-zinc-700 ring-zinc-200")
    return (
        "<span class='inline-flex whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 "
        f"{classes}'>{escape(str(text))}</span>"
    )


def _detail(item: dict) -> str:
    parts = []
    if item.get("repo"):
        parts.append(f"<p>仓库：{escape(str(item['repo']))}</p>")
    if item.get("reason"):
        parts.append(f"<p>{escape(str(item['reason']))}</p>")
    if item.get("web_url"):
        url = escape(str(item["web_url"]))
        parts.append(f'<a class="text-sky-700 underline-offset-2 hover:underline" href="{url}">查看合并请求</a>')
    return "".join(parts) or "—"


def _suggestion(snippet: dict | None) -> str:
    if not snippet:
        return "<span class='text-zinc-400'>—</span>"
    old = escape(str(snippet.get("old_string") or ""))
    new = escape(str(snippet.get("new_string") or ""))
    return (
        "<div class='grid w-full max-w-sm gap-2'>"
        f"<div><p class='mb-1 text-[11px] font-medium uppercase tracking-wide text-zinc-400'>原来</p>"
        f"<pre class='overflow-x-auto rounded-lg bg-zinc-950 px-3 py-2 text-xs text-zinc-100'>{old}</pre></div>"
        f"<div><p class='mb-1 text-[11px] font-medium uppercase tracking-wide text-emerald-700'>改成</p>"
        f"<pre class='overflow-x-auto rounded-lg bg-emerald-950 px-3 py-2 text-xs text-emerald-50'>{new}</pre></div>"
        "</div>"
    )


def _repo_options(choices: list[dict]) -> str:
    if not choices:
        return '<option value="" disabled>填好 Sonar 后刷新页面，这里会列出项目</option>'
    options = []
    for choice in choices:
        selected = " selected" if choice.get("selected") else ""
        key = escape(str(choice.get("key") or ""))
        options.append(f'<option value="{key}"{selected}>{key}</option>')
    return "\n".join(options)
