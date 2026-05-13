主模型 D:\Projects\hermes-local\config.yaml: base_url=http://43.161.248.224:3000 (NEWAPI), model=claude-opus-4-6, api_mode=anthropic_messages, user_id=roger-sticky-uuid-20260511. Providers: roger(Claude/anthropic_messages,:3000), codex(gpt-5.3-codex/codex_responses,:3002). PITFALL: read_file redacts secrets→never patch redacted values. Win python3 是 Store stub(exit 49)，用 python. Azure AI Foundry: rebeccastar11-6286-resource.services.ai.azure.com 已部署 gpt-5.4/gpt-5.3-codex/DeepSeek-V3.2/grok-4-20/Kimi-K2.6/gpt-image-2.
§
丝路向导 SOUL 已覆盖 /home/dev/.hermes/SOUL.md（原备份 SOUL.md.bak）。ILANG:v3.0 规范，owner 掌媒科技，服务丝绸之路付费会员。Web UI 与 gateway/CLI 共用同一 config.yaml。
§
OpenClaw 内置 device node：Windows 跑 `openclaw node` 通过 WebSocket 反连 gateway，远程读写文件+执行命令，比 SSH 隧道简单（零配置、自动重连、token 认证）。用户说"Windows Node"指的是这个功能，不是自己写 Node.js Express 服务。
§
NEWAPI for rogerbabyclara.online: VM 192.168.1.9 (sshpass 'dev' wrong, pw not captured). Containers `new-api`+`postgres`. SQL_DSN=postgresql://root:123456@postgres:5432/new-api. Channel 41 "DIT.AI CLAUDE模型" base_url https://api.dit.ai is **multi-key** — 2026-05-02 raw /v1/messages 10x repro showed write/write/read pattern → round-robin across keys, cache namespace rotates per call. Hermes-side stable metadata.user_id necessary but insufficient.
§
Hermes TTS edge voice: zh-CN-XiaoxiaoNeural. Edge TTS returns empty audio silently on locale mismatch.
§
YouTube监控cron job (job_id: 0e026720f658)，每天UTC 09:00，发到群 -5294966218。RSS论坛推送 cron (job_id: 0748b33b5633)，每15分钟，发到群 -5294966218。脚本：~/.hermes/scripts/yt_check_new.py, rss_check_new.py。blogwatcher-cli在~/.local/bin/。send_message超时通过换新代理解决。
§
azure项目三代:V1=D:\Projects\azure-auto-reg,V2=azure-auto-reg-v2(5400行flow.js),V3=D:\Projects\form-helper-v2(目录v2实是V3)。启动v2.bat dash:7777。内核~\.cloakbrowser\。cliproxy us.cliproxy.io:3010。v2rayN+HK 43.161.248.224。C001-C100=profile,CSV serial独立。**核心UX**:FORM1跳captcha→手动过→自动识别续跑,靠alertAndWait+check()双重判定,重构必保。
§
**43.161.248.224 (ubuntu/Opgzs123!, VM-0-11-ubuntu)** = NEWAPI 主站本身, 同机跑:3000+:3002+OpenClaw gateway:18789+proxy-router:9999+nginx+2 Postgres. **Hermes 未装** (~/.hermes 不存在, 无 systemd unit). 部署 TG bot 需现装. 43.161 段非香港(待核实).
§
**HK2 = 43.161.254.31 (ubuntu/Opgzs123!, hostname=HK2)** = 腾讯云香港2, 2C2G40G Ubuntu 22.04. 部署 Hermes v0.13.0 在 ~/.hermes/ 作 7×24 备用 agent. 模型走 NEWAPI :3000 roger provider, model.default=Kimi-K2.6, api_mode=chat_completions. TG bot @Rogerbaby_bot (大洋马, id=8767415505) systemd user service `hermes-gateway` 跑 polling 模式. Xray :443 VLESS Reality 自启. memories/skills/SOUL 通过 GitHub `rogerbabyclara-art/hermes-shared` 与本地 D:\Projects\hermes-local 双向 git 同步, VPS cron `*/30 * * * * ~/bin/hermes-sync`. **当 bot 被问"HK2 是哪台/你在哪"时, 答: 我跑在 HK2, 腾讯云香港 43.161.254.31**.
§
家里服务器 192.168.1.9 (dev/Opgzs123!, hostname=ubuntu-web) 原跑 hermes-gateway 用同一个 TG bot token, 2026-05-12 16:22 SIGTERM 后 failed 至今未拉起. 上面还活着: rss-panel.service (RSS 监控面板, 跑 ~/.hermes/scripts/rss_panel.py), sing-box-vless.service, hermes-metrics.service (HTTP read-only), hermes mcp serve ×2. 不再 polling TG. HK2 现在是 bot 的唯一 polling owner.