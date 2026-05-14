# no_agent 模式 — 绕过 cron + LLM 的解析坑

## 何时考虑

把 cron 改成 `no_agent: True` 而不是让 LLM 跑，当任一情况发生:

- **本质是字符串格式化** — RSS/YouTube 这类"扫数据 → 按固定模板拼消息 → 发 TG"的任务, LLM 完全是多余的。
- **cron 上下文里 LLM 调用反复失败而 chat/DM 同模型正常** — 表现为:
  - DEBUG_RUNTIME 日志显示 `resolve_runtime_provider` 返回正确 (api_key_present=True, api_mode=anthropic_messages),
  - 但实际请求 dump 显示 `Authorization: 'Bearer None'` (字面值, 不是真的 None)、URL `/chat/completions` (不是 `/v1/messages`)、body 同时含 OpenAI 的 `messages` 和顶层 Anthropic 风格的 `system: <str>` 字段。
  - hermes chat -q "OK" + TG DM 聊天都正常, 唯独 cron 跑挂 → cron 上下文里 AIAgent 内部某处把 api_key/api_mode 弄丢, 这是 hermes-agent 自身 bug, 几小时内修不动。
- **响应模板是固定的** — 任何 LLM 创造性都是干扰 (回顾: 罗总明确要求 RSS 推送只发标题/链接/关键词/时间, 不要总结/分类/重点, 见 SKILL.md "Current prompt format")。

## 怎么改

1. 在 hermes home 写一个**纯 Python 脚本**, 把数据采集 + 格式化 + 输出**一次性**完成。stdout 即最终消息文本。空 stdout = no_agent 自动 silent。
2. 模板见 `scripts/rss_push_noagent.py` (与本 references 同 skill, 已通过 HK2 验证)。
3. 改 `~/.hermes/cron/jobs.json` 把对应 job:
   ```json
   {
     "no_agent": true,
     "script": "rss_push_noagent.py",
     "prompt": "",
     "provider": null,
     "model": null,
     "skills": [],
     "skill": null
   }
   ```
4. `systemctl --user restart hermes-gateway` 让它重读 jobs.json。
5. `hermes cron run <job_id>` 立刻触发, `hermes cron list | grep -A8 <job_id>` 看 `Mode: no-agent (script stdout delivered directly)` 出现就成。

## 已验证 (HK2 43.161.254.31, 2026-05-14)

- 改 no_agent 前: 6 次 cron tick 全 400 (`Bearer None`)
- 改 no_agent 后: 第一次手动触发 `Last run: ok`, `Mode: no-agent (script stdout delivered directly)`, cron output 里直接是格式化好的中文模板。

## 一定要同时检查 TG bot polling 单 owner

`no_agent` 让 cron 跑通**但不保证消息到群**。如果 gateway 日志里反复出现:
```
[Telegram] Telegram polling conflict (1/3), Conflict: terminated by other getUpdates request
```
说明**另一个 hermes-gateway / Web UI 进程也在 polling 同一个 bot token**, TG 会随机切换 getUpdates 的 owner, 你这边发出去的消息 deliver 可能落到那个进程。

排查:
- 本地 Windows: `Get-WmiObject Win32_Process -Filter "name='python.exe'" | Select ProcessId,CommandLine | Format-List` 找 `hermes-webui/server.py` 或 `gateway run` 进程。
- 远程: `ssh <host> "ps -ef | grep -E 'hermes|gateway' | grep -v grep"`。
- 解决: **bot token 只能有一个 owner 在 polling**, 把其他全 kill 或者 disable。HK2 是 7×24 主 owner, 本地 Web UI 和家里 192.168.1.9 都不应该 polling 同一个 token。
