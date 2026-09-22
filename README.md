# ClearDebt

内网服务。它看 Sonar 上 JavaScript 和 TypeScript 的旧告警，检查通过的才开一个小的 GitLab 合并请求。人只在 GitLab 上审。

## 启动

需要本机有 Docker、Git、Node，以及 Python 3.12。

```bash
python3.12 scripts/up.py
```

看到「审核页：http://127.0.0.1:8000/」就打开这个地址。没填接入信息之前，服务碰不到任何仓库。

## 填你自己的 Sonar 和 GitLab

在页面上填你自己的地址和令牌。每个 Sonar 项目写它自己的 GitLab 地址，一行一个。这份仓库里没有别人的账号，也不要把令牌提交进来。更细的步骤在 `启动说明.md`。

## 先空跑

打开「空跑」，保存开关，再执行：

```bash
.venv/bin/python scripts/run_batch.py
```

这一轮只出清算单，不开合并请求。确认没问题后，关掉空跑。

每天上午 8:00，已经启动的工人会自己再跑白名单里的仓库。

## 许可证

MIT，见 `LICENSE`。
