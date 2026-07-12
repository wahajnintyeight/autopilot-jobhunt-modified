# 05 — Integrations

## Telegram and Discord notifications (optional)

After each scan, autopilot can message you the top matches through Telegram or a
Discord webhook. **Entirely optional** — if you skip both, results still save to CSV
and print to the terminal; nothing crashes.

### Set it up

Telegram:

1. Open Telegram, message **@BotFather**, send `/newbot`, follow the prompts.
2. Copy the **bot token** (looks like `8024470769:AAFw…`).
3. Message **@userinfobot** to get your numeric **chat_id** (e.g. `123456789`).

Discord:

1. In Discord, create a webhook for the channel you want.
2. Copy the webhook URL.

### Configure

Add Telegram values to `.env` (or the `telegram` block in `config.json`):

```bash
TELEGRAM_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_numeric_chat_id_here
```

Add Discord to `.env` (or the `discord` block in `config.json`):

```bash
DISCORD_WEBHOOK_URL=your_discord_webhook_url_here
```

Telegram and Discord are independent. Either one can be enabled on its own, and the
same high-scoring matches are sent to whichever notifier is configured. What gets sent:
the top `top_n` matches — company, title, location/remote, stack, one-line reason, and
the apply link. Scan errors (if any) are sent as a separate message when that notifier
is configured.

> **What leaves your machine:** match summaries go to Telegram's servers or your
> Discord webhook, into your own chat/channel. It's a notification only — autopilot
> never applies to anything. See [PRIVACY.md](../PRIVACY.md).

### Verify

Run a scan with Telegram and/or Discord configured — you should receive a "Job Hunt —
<date>" message. If not, check [08 — Troubleshooting](08-troubleshooting.md); a
missing/incorrect token or webhook just means the scan completes without a notification
(results still in the CSV).

## Next

- [06 — MCP server & Skill](06-mcp-and-skill.md)
