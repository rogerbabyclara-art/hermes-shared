User prefers Chinese for troubleshooting and explanations.
§
User requires evidence-based verification with end-to-end proof: live systemd/logs/config checks, real probes, never claim fixed based on parser-only or partial checks.
§
Keep Hermes Web UI/TG/provider/base_url unified; minimal safety-first changes only after live service/config checks. 三层基建观: 工作机Win调试+家庭7x24小服务器跑AI/cron+VPS仅公网入口/中转站, 痛点"VM关AI挂+工作机要关". 全Web化Helper 谨慎(浏览器跑VPS指纹露馅+人工captcha难), 倾向云控本地反向WS架构(VPS大脑+本地手脚).
§
Direct action after agree; ship approved scope first, don't block on later parts ("你先修，修完我告诉你在哪"); admit "没印象/没做过" if session_search empty — NEVER fake recall; bold options. Propagate features to ALL related UIs without asking. Copy-pasteable single commands; no editors/heredocs. UI intent via screenshots — match visual, ask micro-followups. Fingerprint-aware: page-content ≠ expected locale = leak (proxy/tz/WebRTC), NEVER add Chinese regex — audit per fingerprint-audit-checklist.md.
§
User is sensitive to context loss across interrupted sessions; proactively recover with session_search and a concise recap.
§
User's preferred nickname is 罗总. Use 罗总 in casual banter.
§
RSS论坛帖子推送格式偏好：只发标题、链接、匹配关键词、发布时间；不要摘要/分类/重点/一句话总结，依赖 Telegram 链接预览生成缩略简介。