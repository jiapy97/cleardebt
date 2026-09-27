"""Small, scoped tools available to the autonomous repair model."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from cleardebt.fake_fix import review_patch
from cleardebt.languages import is_test_path
from cleardebt.triage import describe

MAX_FILE_BYTES = 256_000
MAX_RESULT_CHARS = 12_000
BLOCKED_PARTS = {".git", ".github", "node_modules", "coverage", "dist", "build", "target", "bin", "obj", ".venv"}
BLOCKED_WRITES = {"sonar-project.properties", "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml"}
BLOCKED_READS = {".token", "id_rsa", "id_ed25519", "credentials", "credentials.json"}


class ToolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


TOOLS = [
    _schema("get_issue_context", "读取当前 Sonar 告警、规则和位置。", {}),
    _schema("search_repo", "按字面量搜索当前仓库。", {
        "query": {"type": "string"}, "glob": {"type": "string"}, "limit": {"type": "integer"},
    }, ["query"]),
    _schema("find_references", "在仓库中搜索符号的引用。", {
        "symbol": {"type": "string"}, "glob": {"type": "string"}, "limit": {"type": "integer"},
    }, ["symbol"]),
    _schema("read_file", "读取仓库文件的指定行，并返回全文 SHA-256 供补丁使用。", {
        "path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"},
    }, ["path"]),
    _schema("get_diff", "查看本次任务已修改的全部文件及 diff。", {}),
    _schema("apply_patch", "按文件 SHA-256 和唯一原文应用多文件精确替换。", {
        "files": {
            "type": "array", "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"}, "expected_sha256": {"type": "string"},
                    "edits": {
                        "type": "array", "minItems": 1, "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {"old_string": {"type": "string"}, "new_string": {"type": "string"}},
                            "required": ["old_string", "new_string"], "additionalProperties": False,
                        },
                    },
                },
                "required": ["path", "expected_sha256", "edits"], "additionalProperties": False,
            },
        },
    }, ["files"]),
    _schema("run_checks", "检查当前补丁。quick 做防作弊检查；full 做防作弊、Sonar 和测试。", {
        "level": {"type": "string", "enum": ["quick", "full"]},
    }, ["level"]),
    _schema("report_blocker", "无法确定安全改法时，说明具体阻碍并结束本条告警。", {
        "reason": {"type": "string"},
    }, ["reason"]),
]


def sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AgentTools:
    def __init__(self, state: dict, *, check: Callable[[dict, str], tuple[dict, dict]] | None = None,
                 call_id: str = ""):
        self.state = state
        self.root = Path(state["work_dir"]).resolve()
        self.check = check
        self.call_id = call_id

    def execute(self, name: str, args: dict) -> tuple[dict, dict]:
        try:
            if name == "get_issue_context":
                data, update = self.issue_context(), {}
            elif name == "search_repo":
                data, update = self.search(args.get("query"), args.get("glob"), args.get("limit")), {}
            elif name == "find_references":
                data, update = self.search(args.get("symbol"), args.get("glob"), args.get("limit")), {}
            elif name == "read_file":
                data, update = self.read(args.get("path"), args.get("start_line"), args.get("end_line")), {}
            elif name == "get_diff":
                data, update = self.diff(), {}
            elif name == "apply_patch":
                data, update = self.apply(args.get("files"))
            elif name == "run_checks":
                if self.check is None:
                    raise ToolError("unavailable", "检查工具尚未接入")
                level = args.get("level")
                if level not in {"quick", "full"}:
                    raise ToolError("invalid_arguments", "level 只能是 quick 或 full")
                data, update = self.check(self.state, level)
            elif name == "report_blocker":
                reason = args.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    raise ToolError("invalid_arguments", "需要说明无法安全修复的原因")
                reason = reason.strip()[:500]
                data, update = {"reason": reason}, {"model_error": f"无法安全修复：{reason}"}
            else:
                raise ToolError("unknown_tool", f"没有工具 {name}")
            return {"ok": True, "data": data}, update
        except ToolError as error:
            return {"ok": False, "error_code": error.code, "summary": str(error)}, {}

    def _path(self, value: object, *, write: bool = False) -> tuple[str, Path]:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ToolError("invalid_path", "文件路径无效")
        relative = Path(value)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise ToolError("invalid_path", "只允许仓库内相对路径")
        if any(part in BLOCKED_PARTS for part in relative.parts):
            raise ToolError("blocked_path", "该目录不允许访问")
        target = self.root / relative
        resolved = target.resolve()
        if target.is_symlink() or not target.is_file() or self.root not in resolved.parents:
            raise ToolError("invalid_path", "文件不存在或路径超出仓库")
        actual = resolved.relative_to(self.root)
        if any(part in BLOCKED_PARTS for part in actual.parts):
            raise ToolError("blocked_path", "该目录不允许访问")
        if actual.name in BLOCKED_READS or actual.name.startswith(".env"):
            raise ToolError("blocked_path", "凭据文件不允许读取")
        if write and (
            is_test_path(value) or is_test_path(actual.as_posix())
            or any(part.lower() in {"test", "tests", "__tests__", "spec", "specs"} for part in actual.parts)
            or actual.name in BLOCKED_WRITES
        ):
            raise ToolError("blocked_path", "测试、扫描配置、依赖或环境文件不允许由 AI 修改")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ToolError("file_too_large", "文件过大，请缩小处理范围")
        return relative.as_posix(), target

    def _text(self, target: Path) -> str:
        try:
            return target.read_text(encoding="utf-8")
        except (UnicodeError, OSError) as error:
            raise ToolError("unreadable", "文件无法按 UTF-8 读取") from error

    def issue_context(self) -> dict:
        from cleardebt.evidence import collect

        path = self.state.get("path") or ""
        _name, target = self._path(path)
        source = self._text(target)
        evidence = collect(
            self.state.get("rule") or "", source, path,
            message=self.state.get("message") or "",
            start_line=self.state.get("start_line"), end_line=self.state.get("end_line"),
        )
        evidence = {
            key: value[:6000] if isinstance(value, str) else value[:12] if isinstance(value, list) else value
            for key, value in evidence.items()
        }
        context = {
            "rule": self.state.get("rule"), "description": describe(self.state.get("rule") or ""),
            "path": self.state.get("path"), "message": self.state.get("message"),
            "start_line": self.state.get("start_line"), "end_line": self.state.get("end_line"),
            "evidence": evidence,
        }
        from cleardebt.controls import load_controls

        if load_controls().get("retrieve"):
            from cleardebt.examples import same_rule_examples

            context["examples"] = same_rule_examples(self.state.get("rule") or "")
        return context

    def read(self, path: object, start_line: object = None, end_line: object = None) -> dict:
        name, target = self._path(path)
        content = self._text(target)
        lines = content.splitlines()
        try:
            start = max(1, int(start_line or 1))
            end = min(len(lines), int(end_line or start + 79), start + 119)
        except (TypeError, ValueError) as error:
            raise ToolError("invalid_arguments", "行号必须是整数") from error
        if end < start:
            raise ToolError("invalid_arguments", "结束行不能早于起始行")
        excerpt = "\n".join(f"{i}|{lines[i - 1]}" for i in range(start, end + 1))
        return {"path": name, "sha256": sha256(content), "total_lines": len(lines),
                "start_line": start, "end_line": end, "content": excerpt[:MAX_RESULT_CHARS]}

    def search(self, query: object, glob: object = None, limit: object = None) -> dict:
        if not isinstance(query, str) or not query.strip() or len(query) > 160:
            raise ToolError("invalid_arguments", "查询词必须是 1–160 个字符")
        try:
            count = min(40, max(1, int(limit or 20)))
        except (TypeError, ValueError) as error:
            raise ToolError("invalid_arguments", "limit 必须是整数") from error
        command = ["rg", "--fixed-strings", "--line-number", "--no-heading", "--max-columns", "240"]
        if glob:
            if not isinstance(glob, str) or len(glob) > 120 or glob.startswith("/") or ".." in glob:
                raise ToolError("invalid_arguments", "文件范围无效")
            command += ["--glob", glob]
        for excluded in (".git/**", "node_modules/**", "coverage/**", "dist/**", "build/**",
                         "target/**", ".env*", "*.token", "credentials.json", "id_rsa", "id_ed25519"):
            command += ["--glob", "!" + excluded]
        command += ["--", query, "."]
        try:
            run = subprocess.run(command, cwd=self.root, text=True, capture_output=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ToolError("search_failed", "仓库搜索未完成") from error
        if run.returncode not in {0, 1}:
            raise ToolError("search_failed", (run.stderr or "仓库搜索失败")[:300])
        matches = run.stdout.splitlines()
        return {"matches": matches[:count], "truncated": len(matches) > count}

    def diff(self) -> dict:
        output = []
        for item in self.state.get("changed_files") or []:
            name, target = self._path(item.get("path"))
            after = self._text(target)
            output.extend(difflib.unified_diff(
                (item.get("before") or "").splitlines(), after.splitlines(),
                fromfile=f"a/{name}", tofile=f"b/{name}", lineterm="",
            ))
        return {"diff": "\n".join(output)[:MAX_RESULT_CHARS], "files": len(self.state.get("changed_files") or [])}

    def apply(self, files: object) -> tuple[dict, dict]:
        if not isinstance(files, list) or not 1 <= len(files) <= 4:
            raise ToolError("invalid_arguments", "一次需要修改 1–4 个文件")
        receipt_path = self._receipt_path()
        args_hash = sha256(json.dumps(files, ensure_ascii=False, sort_keys=True))
        if receipt_path and receipt_path.is_file():
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("args_hash") != args_hash:
                raise ToolError("duplicate_call_id", "同一工具调用 ID 的参数发生变化")
            self._write_receipt_files(receipt["writes"])
            return receipt["result"], receipt["update"]
        previous = {item["path"]: item for item in self.state.get("changed_files") or []}
        prepared: list[tuple[str, Path, str, str]] = []
        seen = set()
        first_edit = None
        for item in files:
            if not isinstance(item, dict):
                raise ToolError("invalid_arguments", "文件编辑格式错误")
            name, target = self._path(item.get("path"), write=True)
            if name in seen:
                raise ToolError("invalid_arguments", "同一文件请放在一个 files 项里")
            seen.add(name)
            before = self._text(target)
            if item.get("expected_sha256") != sha256(before):
                raise ToolError("stale_file", f"{name} 已变化，请重新读取文件")
            edits = item.get("edits")
            if not isinstance(edits, list) or not 1 <= len(edits) <= 8:
                raise ToolError("invalid_arguments", "每个文件需要 1–8 处替换")
            after = before
            for edit in edits:
                if not isinstance(edit, dict):
                    raise ToolError("invalid_arguments", "替换格式错误")
                old, new = edit.get("old_string"), edit.get("new_string")
                if not isinstance(old, str) or not isinstance(new, str) or not old or old == new:
                    raise ToolError("invalid_arguments", "替换原文与新文必须是不同的字符串")
                if after.count(old) != 1:
                    raise ToolError("non_unique", f"{name} 中原文出现 {after.count(old)} 次")
                after = after.replace(old, new, 1)
                first_edit = first_edit or (old, new)
            prepared.append((name, target, before, after))
        candidates = dict(previous)
        for name, _target, before, after in prepared:
            candidates[name] = {"path": name, "before": previous.get(name, {}).get("before", before), "after": after}
        candidates = {name: item for name, item in candidates.items() if item["before"] != item["after"]}
        if not candidates:
            raise ToolError("empty_patch", "补丁没有留下任何改动")
        rejections = review_patch([(item["path"], item["before"], item["after"]) for item in candidates.values()])
        if rejections:
            raise ToolError("rejected_patch", rejections[0].get("reason") or "补丁被防作弊检查拒绝")
        primary = self.state.get("path") or ""
        primary_item = candidates.get(primary)
        update = {
            "changed_files": list(candidates.values()), "fix_method": "agent",
            "proposed_old": (first_edit or ("", ""))[0], "proposed_new": (first_edit or ("", ""))[1],
            "before": primary_item["before"] if primary_item else self.state.get("before") or "",
            "after": primary_item["after"] if primary_item else self.state.get("after") or "",
            "rescan_ok": False, "rescan_executed": False,
            "rescan_removed": [], "rescan_added": [],
            "tests_passed": False, "tests_skipped": False, "tests_executed": False,
            "uncovered_lines": [],
            "agent_verified": False, "model_error": "", "rejections": [],
        }
        result = {"files": [name for name, *_ in prepared], "changed_files": len(candidates)}
        writes = [{"path": name, "before": before, "after": after} for name, _target, before, after in prepared]
        if receipt_path:
            receipt_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=receipt_path.parent, delete=False) as handle:
                json.dump({
                    "args_hash": args_hash, "tool_index": int(self.state.get("agent_tool_count") or 0) + 1,
                    "writes": writes, "result": result, "update": update,
                }, handle, ensure_ascii=False)
                temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            temporary.replace(receipt_path)
        self._write_receipt_files(writes)
        return result, update

    def _receipt_path(self) -> Path | None:
        if not self.call_id:
            return None
        name = hashlib.sha256(self.call_id.encode("utf-8")).hexdigest()
        return self.root.parent / ".agent-receipts" / self.root.name / f"{name}.json"

    def _write_receipt_files(self, writes: list[dict]) -> None:
        """Complete an interrupted multi-file write or replay its saved result."""
        prepared = []
        for item in writes:
            _name, target = self._path(item["path"], write=True)
            current = self._text(target)
            if current not in {item["before"], item["after"]}:
                raise ToolError("stale_file", "工作区在补丁执行后发生了其他变化")
            prepared.append((target, current, item["after"]))
        written = []
        try:
            for target, current, after in prepared:
                if current == after:
                    continue
                with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False) as handle:
                    handle.write(after)
                    temporary = Path(handle.name)
                os.chmod(temporary, target.stat().st_mode)
                temporary.replace(target)
                written.append((target, current))
        except OSError as error:
            for target, before in reversed(written):
                target.write_text(before, encoding="utf-8")
            raise ToolError("write_failed", "补丁写入失败，已恢复原文件") from error


def replay_receipts(state: dict) -> None:
    """Restore accepted patch tool effects after a worktree is recreated."""
    toolbox = AgentTools(state)
    folder = toolbox.root.parent / ".agent-receipts" / toolbox.root.name
    if not folder.is_dir():
        return
    receipts = [json.loads(path.read_text(encoding="utf-8")) for path in folder.glob("*.json")]
    for receipt in sorted(receipts, key=lambda item: int(item.get("tool_index") or 0)):
        toolbox._write_receipt_files(receipt["writes"])
