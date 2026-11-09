# Lords Mobile GF Discord Bot

24/7 Discord bot for **Lords Mobile Guild Fest** (GF) notifications. Posts slot start times, reminders, and member assignments directly to your Discord server.

## Features

| Command | Description |
|---|---|
| `/loot-unregister <ign>` | Remove an IGN from the mappings |
| `/loot-map <ign> <@user>` | Map an IGN to a Discord user |
| `/loot-members` | List all IGN-to-Discord mappings |
| `/loot-test <slot>` | Send a test notification for a slot |
| `/loot-refresh` | Re-sync with the live Google Sheet immediately |
| `/loot-set-start <YYYY-MM-DD>` | Override the Guild Fest start date |
| `/loot-set-tz <timezone>` | Set your personal timezone (e.g. IST, EST, PST, Europe/London) |
| `/loot-my-tz` | Check your currently configured timezone |
| `/loot-remove-tz` | Reset your timezone preference to default dynamic timestamps |
| `/loot-set-tz-user <user> <timezone>` | Admin: Set timezone for another user (requires Administrator) |
| `/loot-status` | Show current GF status and next active slot |
| `/loot-slot <slot>` | Show details for a specific slot |
| `/loot-monster-rotation` | Show the complete GF schedule: slots, times, hunters, monsters |
| `/loot-scan` | Scan server nicknames to link Discord IDs to in-game names |

## One-Click Setup (MSI Cubi NUC)

### Before You Begin
- **Discord Bot Token** — get from [Discord Developer Portal](https://discord.com/developers/applications)
- **Google Sheet** — must be shared with your bot service account email or publicly readable
- **Discord Channel ID** — enable Developer Mode in Discord → right-click channel → "Copy ID"
- **Discord Webhook URL** — optional, for webhook mode

### Step 1: Download

```bash
git clone https://github.com/yourusername/lords-mobile-gf-bot.git
cd lords-mobile-gf-bot
```

Or download ZIP → extract to `C:\bots\gf-bot\`

### Step 2: One-Click Bootstrap

Right-click **run as administrator** and execute `bootstrap.bat`:

```
bootstrap.bat  →  Right-click → "Run as administrator"
```

This will:
1. **Install Python 3.12** automatically (downloads from python.org if not present)
2. **Install dependencies** from `requirements.txt` (discord.py, requests, pytz, python-dateutil)
3. **Prompt for secrets** — enter your Google Sheet URL, Discord bot token, channel ID, and webhook URL
4. **Auto-generate `config.json`** with all defaults (timezone, slot count, reminder minutes, fallback date)
5. **Auto-create runtime files** — `member_mappings.json`, `sent_alerts.json`, `bot.log`, `bot_err.log`
6. **Create Windows scheduled task** — auto-starts at Windows login (runs as Administrator)
7. **Start the bot** immediately

### Step 3: Configure Secrets (Manual)

Edit `config.json` or run `setup.bat`:

```json
{
  "sheet_url": "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit",
  "discord_bot_token": "YOUR_DISCORD_BOT_TOKEN",
  "discord_channel_id": "YOUR_CHANNEL_ID",
  "discord_webhook_url": "YOUR_WEBHOOK_URL"
}
```

### Step 4: BIOS Settings (24/7)

For MSI Cubi NUC continuous operation:
1. **Wake on LAN** = Enabled
2. **ERP Ready** = Disabled
3. **Auto Power-On** = Enabled (power loss recovery)
4. **Fast Boot** = Disabled (for reliable boot)

### Step 5: Verify

On the NUC:
```bat
tasklist | findstr python
```
Should show `python.exe` running. The bot should appear online on your Discord server.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                    bot.py                        │
│  ├── Discord slash commands (13 commands)       │
│  ├── Slot check loop (2-min refresh)            │
│  ├── Scheduler auto-refresh                     │
│  └── Auto-restart on failure                    │
├─────────────────────────────────────────────────┤
│        sheet_parser.py                          │
│  ├── Parses Google Sheet rosters                │
│  ├── Dynamic slot count (any number of slots)  │
│  └── Leftmost-tab selection                     │
├─────────────────────────────────────────────────┤
│        scheduler.py                             │
│  ├── 8-hour IST slots calculation               │
│  ├── Reminder + start alerts                    │
│  └── Alert state tracking                       │
└─────────────────────────────────────────────────┘
```

## Auto-Restart Mechanism

`run_bot_permanent.bat` maintains a restart loop with these safeguards:
- **Duplicate detection**: Checks for existing `bot.py` process before starting
- **Auto-restart**: If the bot crashes, restarts after 10-second delay
- **Log capture**: All output goes to `bot.log`

Windows scheduled task (`BloodMafiaGFBot`):
- Trigger: At Windows login
- Runs with highest privileges
- No battery restrictions (safe for 24/7 desktop)

## Manual Commands

| Command | Purpose |
|---|---|
| `run_bot.bat` | Start bot in foreground (for testing) |
| `run_bot_permanent.bat` | Start with auto-restart loop |
| `setup.bat` | Re-configure bot token and channel ID |
| `install_task.bat` | (Admin) Create/replace scheduled task |
| `bootstrap.bat` | Full one-click setup |

## Troubleshooting

**Bot won't start:**
```bat
python bot.py    →  Check for error messages
type bot.log     →  View recent logs
```

**Commands not showing in Discord:**
- Wait up to 1 hour for global sync
- Run `schtasks /run /tn "BloodMafiaGFBot"` to restart the bot and trigger re-sync

**Sheet not parsing:**
- Verify `sheet_url` in `config.json`
- Ensure sheet is publicly readable or shared with your service account
- Run `test_parser_live.py` to debug

## License

Internal use only. Do not distribute the bot token.
