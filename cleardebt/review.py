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
    "C": "bg-zinc-100 text-zinc-700 ring-zinc-200",
}

_ACTION_CLASS = {
    "already": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "opened": "bg-emerald-50 text-emerald-800 ring-emerald-200",
    "held": "bg-amber-50 text-amber-800 ring-amber-200",
    "no_mr": "bg-zinc-100 text-zinc-700 ring-zinc-200",
    "dry_run": "bg-sky-50 text-sky-800 ring-sky-200",
    "open": "bg-sky-50 text-sky-800 ring-sky-200",
}


def render_page(sheet: dict | None, settings: dict | None = None, error: str = "") -> str:
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
    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClearDebt</title>
<link rel="stylesheet" href="/static/app.css?v=3">
<style>
.toggle-row {{ display:flex; width:100%; box-sizing:border-box; align-items:center; gap:0.75rem; padding:0.75rem 1rem; }}
.toggle-control {{ position:relative; flex:0 0 2.75rem; width:2.75rem; height:1.5rem; }}
.toggle-input {{ position:absolute; opacity:0; width:100%; height:100%; margin:0; cursor:pointer; }}
.toggle-track {{ display:block; width:2.75rem; height:1.5rem; border-radius:999px; background:#d4d4d8; }}
.toggle-knob {{ position:absolute; left:0.125rem; top:0.125rem; width:1.25rem; height:1.25rem; border-radius:999px; background:#fff; box-shadow:0 1px 2px rgb(0 0 0 / 0.2); }}
.toggle-input:checked + .toggle-track {{ background:#18181b; }}
.toggle-input:checked + .toggle-track + .toggle-knob {{ transform:translateX(1.25rem); }}
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
{_toggle("retrieve", retrieve, "检索旧例子", "打开之后，要看上下文的规则会带上以前改过的片段。关掉也能跑，只是提示词里没有。")}
<button type="submit" class="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-800">保存开关</button>
</form>
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
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="sonar_token" type="text" name="sonar_token" value="{escape(settings.get('sonar_token') or '')}" required>
</div>
<div class="sm:col-span-2">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="gitlab_token">GitLab 令牌</label>
<input class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="gitlab_token" type="text" name="gitlab_token" value="{escape(settings.get('gitlab_token') or '')}" required>
</div>
<div class="sm:col-span-2">
<label class="mb-1 block text-sm font-medium text-zinc-700" for="bindings">每个仓库的 GitLab 地址</label>
<textarea class="w-full rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none ring-zinc-900 focus:ring-2" id="bindings" name="bindings" rows="5" placeholder="my-service https://gitlab.com/组/项目">{escape(settings.get('binding_lines') or '')}</textarea>
<p class="mt-2 text-sm text-zinc-500">一行一个。先写 Sonar 项目 key，空一格，再写这个项目自己的 GitLab 地址。没写地址的会跳过，不会去改另一个仓库。</p>
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
</body>
</html>
"""


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
