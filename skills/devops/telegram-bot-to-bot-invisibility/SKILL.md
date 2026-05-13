---
name: telegram-bot-to-bot-invisibility
description: Diagnose and design around the Telegram Bot API rule that one bot cannot receive messages sent by another bot. Use when planning or debugging bot-to-bot relay flows (e.g. an RSS/scraper bot pushes to a chat and a second bot is expected to read and react), or when a second bot in a group is silently missing inbound messages despite correct tokens, group membership, and privacy settings.
---

# Telegram: one bot cannot see another bot's messages

## The hard platform rule

Telegram Bot API **does not deliver `message` updates from bot authors to other bots via `getUpdates` or webhooks.** This is a platform-level rule, not a configuration issue. Symptoms:

- Bot A (e.g. a feed pusher) successfully sends messages to a group.
- Bot B is in the same group with `can_read_all_group_messages=true` (Group Privacy disabled in BotFather).
- Bot B's `getUpdates` / handler logs show zero inbound events from Bot A's messages.
- Human user messages in the same group **do** reach Bot B.

If you see this pattern, stop debugging tokens, privacy, chat IDs, proxy, or `require_mention` — none of that can fix it.

## How to confirm quickly

1. Check Bot B's inbound log for entries tied to the group `chat=<group_id>`. If only human-authored messages appear and none from Bot A, that's the fingerprint.
2. Verify Bot B privacy is already off:
   ```bash
   curl --socks5-hostname 127.0.0.1:PROXY_PORT \
     "https://api.telegram.org/bot<TOKEN_B>/getMe" \
     | jq '.result.can_read_all_group_messages'
   ```
   If `true` and you still get nothing from Bot A, it's the platform rule.
3. Have a human type a message — it arrives. Have Bot A post — it doesn't. Confirmed.

## Architectural alternatives (choose one)

Trade-offs in rough order of simplicity:

### A. Producer does its own work; no relay
Put summarization / enrichment / reaction logic directly in the producer (Bot A) before it sends. One message, no relay needed. Best when the second bot's only job is transformation.

- Pro: minimal infra, no cross-bot coupling, single message in the chat.
- Con: couples business logic into the producer.

### B. Producer → HTTP/webhook → Consumer bot sends
Bot A POSTs payloads to Consumer's HTTP endpoint; Consumer processes and sends its own Telegram message. Skip Telegram as the transport between bots.

- Pro: keeps logic separated; Consumer can still post to the chat.
- Con: requires Consumer to expose an HTTP endpoint (for Hermes, see `webhook-subscriptions` skill).

### C. Producer reads Consumer's data directly
Consumer polls the Producer's database / RSS / API on a schedule and acts. Skip the Telegram round-trip entirely.

- Pro: clean separation, no bot-to-bot dependency.
- Con: adds a scheduler or polling loop on Consumer side.

### D. Producer uses a user account (MTProto), not a bot
Replace Bot A with a Telethon/Pyrogram userbot signed in with a phone number. User messages **are** visible to other bots. Consumer bot now sees everything.

- Pro: preserves the "everything flows through Telegram" design.
- Con: userbot accounts need a phone number, session file, and extra runtime; operationally heavier and against Telegram ToS for automation in some interpretations.

## Pitfalls

- **Do not waste time on Group Privacy.** Turning it off only affects whether the bot sees human messages it wasn't mentioned in. It has zero effect on bot-authored messages.
- **Do not assume `allowed_updates` helps.** Adding `channel_post` or tweaking the list won't unlock bot-authored messages in groups.
- **Channel posts behave differently.** If Bot A posts to a *channel* (not a group) and Bot B is an admin in that channel, Bot B can receive `channel_post` updates. This is the one exception — but it requires both bots to be channel admins, and most "group chat with two bots" setups aren't using channels.
- **Forwarded messages are not a workaround.** Forwarding a bot message into the group still shows the original author; it doesn't reset visibility rules for the recipient bot.
- **Assistant bots with MTProto clients on the backend (e.g. moderation bots that use a user session under the hood) can see bot messages** — but that's because they're not using the Bot API for reads. Same as option D.

## Option D operational notes (Telethon userbot)

If you go with option D and use Telethon with a SOCKS5 proxy:

- **Use `PySocks`, not `python-socks`.** Telethon's `proxy=("socks5", host, port)` tuple interface routes through PySocks. Installing `python-socks[asyncio]` instead leaves PySocks missing; `client.connect()` then **hangs silently with zero log output**, even at DEBUG level — easy to mistake for a network or credentials issue. Verify with `python3 -c \"import socks; print(socks.__version__)\"`. If that fails, `pip install PySocks`.
- **Public api_id/api_hash are usable.** `my.telegram.org` often returns a generic `ERROR` for new/low-reputation accounts with no further detail. The Telegram Desktop open-source pair (`api_id=2040`, `api_hash=b18441a1ff607e10a989891a5462e627`) is widely used and works for any account login. api_id/api_hash do not bind to the account that registered them.
- **Login is interactive.** `client.send_code_request(phone)` delivers a 5-digit code via `SentCodeTypeApp` (in-app Telegram message from the official "Telegram" account, not SMS) for accounts already logged in elsewhere. If running headless, split login into two steps: stage 1 sends the code and persists `phone_code_hash` to disk; stage 2 takes the code (and 2FA password if `SessionPasswordNeededError`) as CLI args and calls `sign_in`. This avoids fragile PTY/stdin interaction in remote shells.
- **`events.NewMessage(chats=...)` ID format gotcha.** Telethon's `chats=` filter is finicky about signed vs raw IDs across Chat/Channel/User entity types. If the listener silently receives nothing despite being in the chat, drop the filter and check `event.chat_id` inside the handler instead — `event.chat_id` is the signed Bot-API form (e.g. `-5294966218` for a basic group) and is reliable to compare against.
- **Use a burner/secondary account for the userbot.** Userbot behaviour can trigger account-level risk controls; isolate the blast radius from the primary account. The api_id/api_hash itself stays the same regardless of which account logs in.
- **Ignore the *other* assistant bot's messages, not just your own.** If the userbot is added to a chat that *also* contains a regular Hermes/Telegram bot, the bot's replies often contain the same trigger keywords ("hermes", "助手", etc.) and will re-trigger the userbot, producing a bot↔userbot feedback loop. The standard `if sender_id == MY_ID: return` self-skip is not enough. Hard-code the peer bot's user_id and skip it explicitly:\n  ```python\n  if sender_id in (MY_ID, OTHER_HERMES_BOT_ID):\n      return\n  ```\n  Decide up-front who is "the responder" in that chat — usually you want exactly one (either the userbot OR the bot, not both) to avoid duplicate replies regardless of the loop.\n- **Don't use `AIAgent.chat()` for one-shot userbot replies; call the LLM client directly.** `AIAgent` injects a heavy system prompt, tool schemas, skill list, and memory context even with `enabled_toolsets=[]` and `skip_memory=True`. With some upstream routes (e.g. NewAPI fronting a Claude model) this combination can cause the model to return blank content; `chat()` then retries 3× and finally returns the literal string `"(empty)"` (7 chars), which the userbot will happily forward to the chat as three blank messages. Symptom in logs: `replied (7 chars in 1 chunk(s))` followed by users seeing `(empty)` bubbles. Fix: skip `AIAgent` for this use case and call the configured LLM directly. Read `model.base_url`, `model.api_key`, and `model.model` from `~/.hermes/config.yaml`, instantiate `openai.OpenAI(base_url=..., api_key=...)`, and call `chat.completions.create` with a tiny system prompt. Verify the same model works first via `curl` to `<base_url>/v1/chat/completions` — if curl returns content, the issue is AIAgent's request shape, not the upstream.\n- **Reuse the hermes-agent venv instead of building a parallel one.** `AIAgent` (from `run_agent.py`) imports many transitive deps (`fire`, plugin loaders, etc.) that are easy to forget. Running the userbot listener under `/home/dev/.hermes/hermes-agent/.venv/bin/python` and `pip install`ing only the *extra* packages (`telethon`, `PySocks`, `python-socks[asyncio]`) into that same venv is more reliable than creating a fresh venv that adds `hermes-agent` to `sys.path` — the latter throws `ModuleNotFoundError: No module named 'fire'` (and similar) at runtime even though imports look fine at the top of your file. Set `HERMES_HOME` and `PYTHONPATH=/home/dev/.hermes/hermes-agent` in the systemd unit.

## Verification after choosing an alternative

- Option A: check the producer's outbound log shows the enriched content in the single message it sent.
- Option B: check Consumer's HTTP endpoint log received the payload AND Consumer's outbound Telegram log shows the reply message.
- Option C: check Consumer's scheduler log shows it polled and acted within the expected interval.
- Option D: check Consumer bot's inbound log now shows `from=<userbot_username>` messages in the group chat.

## When this skill applies

Trigger on any of:
- Two Telegram bots in the same chat where one should react to the other.
- "Bot is in the group but doesn't see X messages" where X is posted by another bot.
- Designing a pipeline where a scraper/feed/alert bot is the producer and an LLM/agent bot is the consumer, both on Telegram.
- Debugging a previously-working integration after splitting one bot into two.
