"""
Lords Mobile Guild Fest (GF) Discord Bot.
Handles automated slot notifications, member pings, and interactive slash commands.
"""

import os
import sys
import json
import time
import asyncio
import datetime
from typing import Optional, List, Dict

import difflib
import re

import pytz
import discord
from discord import app_commands
from discord.ext import commands, tasks

import sheet_parser
from scheduler import GFScheduler, compute_slot_0_utc, compute_slot_0_ist, IST, PST, UTC
import notifier
from notifier import get_user_timezone
import monster_schedule

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

CONFIG_FILE = "config.json"
MAPPINGS_FILE = "member_mappings.json"
USER_TZ_FILE = "user_timezones.json"
IST = pytz.timezone("Asia/Kolkata")
PST = pytz.timezone("America/Los_Angeles")

POPULAR_TIMEZONES = [
    ("Asia/Kolkata", "Asia/Kolkata (IST - India +5:30)"),
    ("America/Los_Angeles", "America/Los_Angeles (PST/PDT - US West)"),
    ("America/New_York", "America/New_York (EST/EDT - US East)"),
    ("America/Chicago", "America/Chicago (CST/CDT - US Central)"),
    ("America/Denver", "America/Denver (MST/MDT - US Mountain)"),
    ("Europe/London", "Europe/London (GMT/BST - UK)"),
    ("Europe/Paris", "Europe/Paris (CET/CEST - Central Europe)"),
    ("Europe/Berlin", "Europe/Berlin (CET/CEST - Germany)"),
    ("Asia/Manila", "Asia/Manila (PHT - Philippines +8)"),
    ("Asia/Singapore", "Asia/Singapore (SGT - Singapore +8)"),
    ("Asia/Dubai", "Asia/Dubai (GST - UAE +4)"),
    ("Asia/Tokyo", "Asia/Tokyo (JST - Japan +9)"),
    ("Australia/Sydney", "Australia/Sydney (AEST/AEDT - Sydney)"),
    ("America/Sao_Paulo", "America/Sao_Paulo (BRT - Brazil)"),
    ("UTC", "UTC (Coordinated Universal Time)")
]

TIMEZONE_ALIASES = {
    "ist": "Asia/Kolkata",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "est": "America/New_York",
    "edt": "America/New_York",
    "cst": "America/Chicago",
    "cdt": "America/Chicago",
    "mst": "America/Denver",
    "mdt": "America/Denver",
    "utc": "UTC",
    "gmt": "UTC",
    "bst": "Europe/London",
    "cet": "Europe/Paris",
    "cest": "Europe/Paris",
    "eet": "Europe/Athens",
    "sgt": "Asia/Singapore",
    "pht": "Asia/Manila",
    "wib": "Asia/Jakarta",
    "aest": "Australia/Sydney",
    "aedt": "Australia/Sydney",
    "jst": "Asia/Tokyo",
    "kst": "Asia/Seoul",
    "brt": "America/Sao_Paulo",
    "gst": "Asia/Dubai"
}


def load_user_timezones() -> Dict[str, str]:
    if os.path.exists(USER_TZ_FILE):
        try:
            with open(USER_TZ_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading user timezones: {e}")
            return {}
    return {}


def save_user_timezones(tz_map: Dict[str, str]):
    try:
        with open(USER_TZ_FILE, "w", encoding="utf-8") as f:
            json.dump(tz_map, f, indent=2)
    except Exception as e:
        print(f"Error saving user timezones: {e}")


def resolve_timezone(name: str) -> Optional[str]:
    if not name:
        return None
    clean = name.strip()
    clean_lower = clean.lower()
    if clean_lower in TIMEZONE_ALIASES:
        return TIMEZONE_ALIASES[clean_lower]
    for tz in pytz.all_timezones:
        if tz.lower() == clean_lower:
            return tz
    for tz in pytz.common_timezones:
        if clean_lower in tz.lower():
            return tz
    return None


async def timezone_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    current_lower = current.strip().lower()
    choices = []
    for tz_val, label in POPULAR_TIMEZONES:
        if not current_lower or current_lower in label.lower() or current_lower in tz_val.lower():
            choices.append(app_commands.Choice(name=label, value=tz_val))
    if not choices:
        for tz in pytz.common_timezones:
            if current_lower in tz.lower():
                choices.append(app_commands.Choice(name=tz, value=tz))
                if len(choices) >= 25:
                    break
    return choices[:25]


def normalize_name(name: str) -> str:
    """Strips guild tags like [B|M], (R4), and non-alphanumeric chars for clean matching."""
    if not name:
        return ""
    # Remove bracketed tags like [B|M], [bM], (R4), etc.
    cleaned = re.sub(r"\[.*?\]|\(.*?\)", "", name)
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned.lower()


def auto_match_guild_members(guild: discord.Guild, ign_list: list) -> dict:
    """
    Scans guild members' nicknames, display names, and usernames to automatically
    find matching Discord IDs for sheet IGNs. Fully case-insensitive and normalized.
    """
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)
    locked_igns = notifier.load_locked_igns()
    matched_count = 0
    newly_matched = []

    for ign in ign_list:
        clean_ign = ign.strip()
        # If already mapped with a valid numeric ID, skip
        existing_id = notifier.resolve_discord_id(clean_ign, mappings)
        if existing_id:
            continue

        if clean_ign in locked_igns:
            continue

        norm_ign = notifier.normalize_name(clean_ign)
        if not norm_ign:
            continue

        best_match_user = None
        best_ratio = 0.0

        for member in guild.members:
            if member.bot:
                continue

            candidates = [
                member.display_name,
                getattr(member, "global_name", "") or "",
                member.name
            ]

            for cand in candidates:
                if not cand:
                    continue
                norm_cand = notifier.normalize_name(cand)
                if not norm_cand:
                    continue

                # 1. Exact match after normalization (case-insensitive)
                if norm_ign == norm_cand:
                    best_match_user = member
                    best_ratio = 1.0
                    break

                # 2. Substring match
                if len(norm_ign) >= 3 and (norm_ign in norm_cand or norm_cand in norm_ign):
                    ratio = len(norm_ign) / max(len(norm_cand), 1)
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match_user = member

                # 3. Fuzzy similarity
                ratio = difflib.SequenceMatcher(None, norm_ign, norm_cand).ratio()
                if ratio > best_ratio and ratio >= 0.85:
                    best_ratio = ratio
                    best_match_user = member

            if best_ratio == 1.0:
                break

        if best_match_user:
            mappings[clean_ign] = str(best_match_user.id)
            matched_count += 1
            newly_matched.append(clean_ign)
            print(f"[Auto-Matched] '{clean_ign}' -> {best_match_user.display_name} (ID: {best_match_user.id})", flush=True)

    if matched_count > 0:
        notifier.save_member_mappings(mappings, MAPPINGS_FILE)
        # Auto-lock newly matched IGNs so they persist forever
        locked_set = set(locked_igns)
        locked_set.update(newly_matched)
        notifier.save_locked_igns(list(locked_set))
    return mappings


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


intents = discord.Intents.default()
intents.members = True  # Required to scan server member nicknames
intents.message_content = True

bot = commands.Bot(command_prefix="!gf ", intents=intents)
scheduler: Optional[GFScheduler] = None
latest_sheet_data: Optional[dict] = None
last_sheet_fetch_time: float = 0
_last_refresh_sig: Optional[tuple] = None


def refresh_scheduler():
    """Refreshes the scheduler from Google Sheet header date (PST) -> Slot 0 at 05:00 UTC."""
    global scheduler, latest_sheet_data, last_sheet_fetch_time, _last_refresh_sig
    cfg = load_config()
    sheet_url = cfg.get("sheet_url", "")
    try:
        data = sheet_parser.parse_google_sheet(sheet_url)
        latest_sheet_data = data
        last_sheet_fetch_time = time.time()
        detected_date = data.get("header_date")  # PST date from sheet header
        rosters = data.get("rosters", {})
        all_slot_nums = list(rosters.get("BM", {}).keys()) + list(rosters.get("bM", {}).keys())
        total_slots = (max(all_slot_nums) + 1) if all_slot_nums else cfg.get("total_slots", 15)

        if detected_date and cfg.get("auto_detect_date_from_sheet", True):
            slot_0_dt = compute_slot_0_utc(detected_date)
        else:
            fallback = cfg.get("fallback_start_date", "2026-09-06")
            parts = [int(p) for p in fallback.split("-")]
            fb_date = datetime.date(parts[0], parts[1], parts[2])
            slot_0_dt = compute_slot_0_utc(fb_date)

        scheduler = GFScheduler(
            slot_0_start_dt=slot_0_dt,
            total_slots=total_slots,
            reminder_minutes=cfg.get("pre_slot_reminder_minutes", 15),
        )
        sig = (detected_date, slot_0_dt, total_slots)
        if sig != _last_refresh_sig:
            _last_refresh_sig = sig
            print(f"[Scheduler Refreshed] PST header={detected_date} -> Slot 0 UTC={slot_0_dt.strftime('%Y-%m-%d %H:%M:%S %Z')} (05:00 UTC fixed)", flush=True)
    except Exception as e:
        print(f"[Error refreshing scheduler]: {e}", flush=True)


async def get_live_sheet_data(force: bool = False) -> dict:
    """
    Fetches the latest live Google Sheet data.
    Uses a 5-second TTL cache to prevent spamming Google Sheets on rapid commands
    while ensuring any sheet edit is absorbed immediately.
    """
    global latest_sheet_data, last_sheet_fetch_time
    now = time.time()
    if force or latest_sheet_data is None or (now - last_sheet_fetch_time) > 5:
        cfg = load_config()
        sheet_url = cfg.get("sheet_url", "")
        try:
            data = await asyncio.to_thread(sheet_parser.parse_google_sheet, sheet_url)
            latest_sheet_data = data
            last_sheet_fetch_time = now
        except Exception as e:
            print(f"[Warning] Failed to fetch live sheet: {e}", flush=True)
    return latest_sheet_data or {"rosters": {"BM": {}, "bM": {}}}


@bot.event
async def on_error(event, *args, **kwargs):
    import traceback
    print(f"[Error] Unhandled exception in {event}:", flush=True)
    traceback.print_exc()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    import traceback
    print(f"[Command Error] {type(error).__name__}: {error}", flush=True)
    traceback.print_exc()
    try:
        await interaction.followup.send("Command encountered an error.", ephemeral=True)
    except Exception:
        try:
            await interaction.response.send_message("Command encountered an error.", ephemeral=True)
        except Exception as e2:
            print(f"[Command Error] Could not send error response: {e2}", flush=True)


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})", flush=True)
    await asyncio.to_thread(refresh_scheduler)

    # Automatically scan server members and link Discord IDs by nickname
    ign_list = []
    if latest_sheet_data and "rosters" in latest_sheet_data:
        for g_dict in latest_sheet_data["rosters"].values():
            for m_list in g_dict.values():
                ign_list.extend(m_list)
        ign_list = list(set(ign_list))

    for guild in bot.guilds:
        print(f"[*] Scanning server '{guild.name}' ({len(guild.members)} members) to auto-match sheet names...", flush=True)
        await asyncio.to_thread(auto_match_guild_members, guild, ign_list)

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s) globally.", flush=True)
        for guild in bot.guilds:
            try:
                guild_synced = await bot.tree.sync(guild=guild)
                print(f"Synced {len(guild_synced)} command(s) to guild {guild.name}.", flush=True)
            except Exception as e:
                print(f"Guild sync failed for {guild.name}: {e}", flush=True)
    except Exception as e:
        print(f"Failed to sync slash commands: {e}", flush=True)

    # Start background tasks now that event loop is running
    if not slot_check_loop.is_running():
        slot_check_loop.start()
    if not auto_scan_loop.is_running():
        auto_scan_loop.start()
    if not heartbeat_loop.is_running():
        heartbeat_loop.start()

@tasks.loop(seconds=60)
async def auto_scan_loop():
    """Background task running every 60s to auto-scan Google Sheet for new members.
    Automatically links new IGNs to Discord members by nickname matching."""
    try:
        # Skip if not ready
        if scheduler is None or not bot.guilds:
            return
        
        # Refresh scheduler and sheet data
        try:
            await asyncio.to_thread(refresh_scheduler)
            if scheduler is None:
                return
        except Exception as e:
            print(f"[Auto-Scan] Scheduler refresh error: {e}", flush=True)
            return
        
        # Fetch fresh sheet data
        try:
            sheet_data = await get_live_sheet_data(force=True)
            if not sheet_data or "rosters" not in sheet_data:
                return
        except Exception as e:
            print(f"[Auto-Scan] Sheet fetch error: {e}", flush=True)
            return
        
        # Collect all IGNs from sheet
        ign_list = []
        for g_dict in sheet_data.get("rosters", {}).values():
            for m_list in g_dict.values():
                if m_list:
                    ign_list.extend(m_list)
        ign_list = list(set(ign_list))
        
        if not ign_list:
            return
        
        # Load current mappings
        try:
            mappings = notifier.load_member_mappings(MAPPINGS_FILE)
        except Exception as e:
            print(f"[Auto-Scan] Failed to load mappings: {e}", flush=True)
            return
        
        # Find unmapped IGNs
        unmapped = []
        for ign in ign_list:
            try:
                resolved_id = notifier.resolve_discord_id(ign, mappings)
                if not resolved_id or not str(resolved_id).strip().isdigit():
                    unmapped.append(ign)
            except Exception:
                unmapped.append(ign)
        
        if not unmapped:
            return  # All members already mapped
        
        if not bot.guilds:
            return
            
        # Auto-match unmapped IGNs
        updated_mappings = auto_match_guild_members(bot.guilds[0], unmapped)
        matched_now = [ign for ign in unmapped if updated_mappings.get(ign, "").strip().isdigit()]
        
        if matched_now:
            notifier.save_member_mappings(updated_mappings, MAPPINGS_FILE)
            print(f"[Auto-Scan] Mapped {len(matched_now)} new member(s): {matched_now}", flush=True)
            
    except Exception as e:
        print(f"[Auto-Scan] Unexpected error: {e}", flush=True)


@tasks.loop(seconds=30)
async def slot_check_loop():
    """Background task running every 30s to check and dispatch slot notifications.
    Refreshes the scheduler every cycle so a new GF (new sheet/tab date) is auto-detected."""
    global scheduler, latest_sheet_data
    # Auto-refresh every cycle: re-detects the GF start date and pulls fresh rosters,
    # so switching to a new GF tab is picked up without a restart or manual /loot-refresh.
    await asyncio.to_thread(refresh_scheduler)
    if scheduler is None:
        return

    cfg = load_config()
    channel_id_str = cfg.get("discord_channel_id", "")
    webhook_url = cfg.get("discord_webhook_url", "")

    if not channel_id_str and not webhook_url:
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    pending_alerts = scheduler.check_pending_alerts(now)

    if not pending_alerts:
        return

    rosters = latest_sheet_data.get("rosters", {}) if latest_sheet_data else {"BM": {}, "bM": {}}
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)
    user_timezones = notifier.load_user_timezones()

    for alert in pending_alerts:
        slot_num = alert["slot_num"]
        alert_type = alert["type"]
        slot_timing = alert["slot_timing"]

        bm_members = rosters.get("BM", {}).get(slot_num, [])
        lbm_members = rosters.get("bM", {}).get(slot_num, [])

        payload = notifier.build_slot_alert_payload(
            alert_type=alert_type,
            slot_info=slot_timing,
            bm_members=bm_members,
            little_bm_members=lbm_members,
            mappings=mappings,
            user_timezones=user_timezones,
            user_tz_name=None
        )

        # Dispatch to Discord Channel
        sent_ok = False
        if channel_id_str and channel_id_str.isdigit():
            channel = bot.get_channel(int(channel_id_str))
            if channel:
                try:
                    embed_dict = payload["embeds"][0]
                    embed = discord.Embed.from_dict(embed_dict)
                    await channel.send(content=payload["content"], embed=embed)
                    sent_ok = True
                except Exception as e:
                    print(f"Error sending message to channel: {e}", flush=True)

        # Or dispatch to Webhook if configured
        if webhook_url:
            await asyncio.to_thread(notifier.send_discord_webhook, webhook_url, payload)
            sent_ok = True

        if sent_ok:
            scheduler.mark_alert_sent(alert_type, slot_num)
            print(f"[Alert Sent] Slot {slot_num} ({alert_type}) dispatched successfully.", flush=True)


@tasks.loop(seconds=300)
async def heartbeat_loop():
    """Heartbeat to keep bot alive and log status."""
    print(f"[Heartbeat] Bot alive - Guilds: {len(bot.guilds)}, Latency: {bot.latency*1000:.0f}ms", flush=True)


# -------------------------------------------------------------
# Slash Commands
# -------------------------------------------------------------
@bot.tree.command(name="loot-status", description="Check currently active Guild Fest slot, hunters, and countdown.")
async def gf_status(interaction: discord.Interaction):
    global scheduler
    await interaction.response.defer()
    if scheduler is None:
        await asyncio.to_thread(refresh_scheduler)

    now = datetime.datetime.now(datetime.timezone.utc)
    active = scheduler.get_active_slot(now)
    upcoming = scheduler.get_next_slot(now)

    sheet_data = await get_live_sheet_data(force=True)
    rosters = sheet_data.get("rosters", {})
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)

    user_tz_name = get_user_timezone(interaction.user.id)

    embed = discord.Embed(title="🛡️ Guild Fest Status Overview", color=0x3498DB)
    embed.add_field(name="Current Time (Local)", value=f"<t:{int(now.timestamp())}:F>", inline=False)

    if active:
        slot_num = active["slot_num"]
        bm = rosters.get("BM", {}).get(slot_num, [])
        lbm = rosters.get("bM", {}).get(slot_num, [])

        bm_text, _ = notifier.format_guild_section(bm, mappings)
        lbm_text, _ = notifier.format_guild_section(lbm, mappings)

        user_window_str = ""
        if user_tz_name:
            user_window_str = f"**Your Window ({user_tz_name})**: <t:{active['start_ts']}:f> → <t:{active['end_ts']}:t>\n"

        if slot_num == 0:
            embed.color = 0x00FF88
            embed.add_field(
                name=f"🟢 ACTIVE NOW: Slot {slot_num}",
                value=(
                    f"⚔️ **Guild Fest Slot {slot_num} is live, hunt begins after 8 hr take your quest and be ready for slot 1 ⚔️**\n"
                    f"The new 8-hour Guild Fest loot slot has started!\n"
                    f"Ends <t:{active['end_ts']}:R> at **<t:{active['end_ts']}:t>**.\n"
                    f"Please take your legendary loot quests and meet your requirements.\n\n"
                    f"{user_window_str}"
                    f"**Window**: <t:{active['start_ts']}:f> → <t:{active['end_ts']}:t>\n"
                    f"**Time Remaining**: <t:{active['end_ts']}:R> (`{active['remaining_formatted']}`)\n\n"
                    f"👑 **[B|M] Blood Mafia ({len(bm)}/4)**:\n{bm_text}\n\n"
                    f"🛡️ **[b|M] Little Blood Mafia ({len(lbm)}/4)**:\n{lbm_text}"
                ),
                inline=False
            )
        else:
            embed.add_field(
                name=f"🟢 ACTIVE NOW: Slot {slot_num}",
                value=(
                    f"{user_window_str}"
                    f"**Window**: <t:{active['start_ts']}:f> → <t:{active['end_ts']}:t>\n"
                    f"**Time Remaining**: <t:{active['end_ts']}:R> (`{active['remaining_formatted']}`)\n\n"
                    f"👑 **[B|M] Blood Mafia ({len(bm)}/4)**:\n{bm_text}\n\n"
                    f"🛡️ **[b|M] Little Blood Mafia ({len(lbm)}/4)**:\n{lbm_text}"
                ),
                inline=False
            )
    else:
        embed.add_field(name="Status", value="No slot is currently active.", inline=False)

    if upcoming:
        slot_num = upcoming["slot_num"]
        bm = rosters.get("BM", {}).get(slot_num, [])
        lbm = rosters.get("bM", {}).get(slot_num, [])

        user_upcoming_str = ""
        if user_tz_name:
            user_upcoming_str = f"**Your Window ({user_tz_name})**: <t:{upcoming['start_ts']}:f> → <t:{upcoming['end_ts']}:t>\n"

        embed.add_field(
            name=f"⏳ UPCOMING: Slot {slot_num}",
            value=(
                f"**Starts in**: <t:{upcoming['start_ts']}:R> (`{upcoming['until_start_formatted']}`)\n"
                f"{user_upcoming_str}"
                f"**Window**: <t:{upcoming['start_ts']}:f> → <t:{upcoming['end_ts']}:t>\n"
                f"• [B|M]: {len(bm)}/4 hunters\n"
                f"• [b|M]: {len(lbm)}/4 hunters"
            ),
            inline=False
        )

    if user_tz_name:
        embed.set_footer(text=f"Timezone: {user_tz_name} • Change anytime with /loot-set-tz")
    else:
        embed.set_footer(text="💡 Tip: Set your personal timezone using /loot-set-tz")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="loot-slot", description="View hunters and schedule for a specific slot number (0-14).")
@app_commands.describe(slot_number="Slot number from 0 to 14")
async def gf_slot(interaction: discord.Interaction, slot_number: int):
    global scheduler
    if slot_number < 0 or slot_number > 14:
        await interaction.response.send_message("Slot number must be between 0 and 14.", ephemeral=True)
        return

    await interaction.response.defer()
    if scheduler is None:
        await asyncio.to_thread(refresh_scheduler)

    slot_info = scheduler.get_slot_timing(slot_number)
    sheet_data = await get_live_sheet_data(force=True)
    rosters = sheet_data.get("rosters", {})
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)

    bm = rosters.get("BM", {}).get(slot_number, [])
    lbm = rosters.get("bM", {}).get(slot_number, [])

    bm_text, _ = notifier.format_guild_section(bm, mappings)
    lbm_text, _ = notifier.format_guild_section(lbm, mappings)

    user_tz_name = get_user_timezone(interaction.user.id)

    if slot_number == 0:
        embed = discord.Embed(
            title=f"⚔️ Guild Fest Slot {slot_number} is live, hunt begins after 8 hr take your quest and be ready for slot 1 ⚔️",
            description=(
                "The new 8-hour Guild Fest loot slot has started!\n"
                f"Ends <t:{slot_info['end_ts']}:R> at **<t:{slot_info['end_ts']}:t>**.\n"
                "Please take your legendary loot quests and meet your requirements."
            ),
            color=0x00FF88,
        )
    else:
        embed = discord.Embed(
            title=f"⚔️ Guild Fest Slot {slot_number} Details",
            color=0x9B59B6,
        )

    embed.add_field(
        name="⏰ Time Window",
        value=f"**<t:{slot_info['start_ts']}:f> → <t:{slot_info['end_ts']}:t>** (<t:{slot_info['start_ts']}:R>)",
        inline=False
    )
    embed.add_field(name=f"👑 [B|M] Blood Mafia ({len(bm)}/4)", value=bm_text, inline=True)
    embed.add_field(name=f"🛡️ [b|M] Little Blood Mafia ({len(lbm)}/4)", value=lbm_text, inline=True)

    if user_tz_name:
        embed.set_footer(text=f"Timezone: {user_tz_name} • Change with /loot-set-tz")
    else:
        embed.set_footer(text="💡 Tip: Set your personal timezone using /loot-set-tz")

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="loot-monster-rotation", description="Complete GF schedule: slots, local times, hunters, and monsters (instant).")
async def gf_monster_rotation(interaction: discord.Interaction):
    print(f"[loot-monster-rotation] Invoked by user {interaction.user.id} in guild {interaction.guild_id}", flush=True)
    try:
        if not interaction.response.is_done():
            await interaction.response.defer()
            print("[loot-monster-rotation] Deferred OK", flush=True)
    except Exception as e:
        print(f"[loot-monster-rotation] Defer failed: {e}", flush=True)

    if scheduler is None:
        await asyncio.to_thread(refresh_scheduler)

    if scheduler is None:
        try:
            await interaction.followup.send("GF start date not available. Run `/loot-refresh` first.")
        except Exception:
            try:
                await interaction.response.send_message("GF start date not available. Run `/loot-refresh` first.")
            except Exception:
                pass
        return

    try:
        gf_start = scheduler.slot_0_start_utc if hasattr(scheduler, 'slot_0_start_utc') else scheduler.slot_0_start.astimezone(datetime.timezone.utc)

        schedule = monster_schedule.get_monster_schedule()
        if not schedule or "days" not in schedule:
            try:
                await interaction.followup.send("Could not load monster schedule.")
            except Exception:
                try:
                    await interaction.response.send_message("Could not load monster schedule.")
                except Exception:
                    pass
            return

        sheet_data = await get_live_sheet_data(force=True)
        rosters = sheet_data.get("rosters", {}) if sheet_data else {"BM": {}, "bM": {}}

        now_utc = datetime.datetime.now(datetime.timezone.utc)
        elapsed_hours = (now_utc - gf_start).total_seconds() / 3600
        current_slot = min(int(elapsed_hours // 8) if elapsed_hours >= 0 else 0, 14)
        current_gf_day = current_slot // 3 + 1

        days = schedule["days"]

        # Compute base_day_index from PST header date (GF start day = header + 1)
        detected = (latest_sheet_data or {}).get("header_date")
        if detected:
            gf_start_date = detected + datetime.timedelta(days=1)
        else:
            gf_start_date = gf_start.astimezone(PST).date()
        base_day_index = monster_schedule.get_day_index_for_date(gf_start_date)

        # Build slot data for all 15 slots
        slot_data = []
        for slot_num in range(15):
            timing = scheduler.get_slot_timing(slot_num)
            day_idx = (base_day_index + (slot_num // 3)) % 12
            day = days[day_idx]
            monster_names = " & ".join([m["name"] for m in day["monsters"]])

            bm_count = len(rosters.get("BM", {}).get(slot_num, []))
            lbm_count = len(rosters.get("bM", {}).get(slot_num, []))

            start_ts = timing["start_ts"]
            end_ts = timing["end_ts"]

            is_current = slot_num == current_slot
            slot_data.append({
                "slot_num": slot_num,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "monster_names": monster_names,
                "bm_count": bm_count,
                "lbm_count": lbm_count,
                "is_current": is_current
            })

        # ── Message 1: Slots 0-7 ──────────────────────────────────────
        embed1 = discord.Embed(title="Guild Fest Schedule", color=0x3498DB)
        embed1.description = (
            f"Starts: <t:{int(gf_start.timestamp())}:f> | "
            f"Current Day: {current_gf_day}/5 | "
            f"Current Slot: {current_slot}"
        )
        for s in slot_data[:8]:
            marker = " ⚡ NOW" if s["is_current"] else ""
            field_name = f"Slot {s['slot_num']}{marker}"
            field_value = (
                f"<t:{s['start_ts']}:f> → <t:{s['end_ts']}:t>\n"
                f"{s['monster_names']}\n"
                f"[B\\|M] {s['bm_count']}/4  |  [b\\|M] {s['lbm_count']}/4"
            )
            embed1.add_field(name=field_name, value=field_value, inline=False)

        # ── Message 2: Slots 8-14 + Footer ────────────────────────────
        embed2 = discord.Embed(title="Guild Fest Schedule (Continued)", color=0x9B59B6)
        for s in slot_data[8:]:
            marker = " ⚡ NOW" if s["is_current"] else ""
            field_name = f"Slot {s['slot_num']}{marker}"
            field_value = (
                f"<t:{s['start_ts']}:f> → <t:{s['end_ts']}:t>\n"
                f"{s['monster_names']}\n"
                f"[B\\|M] {s['bm_count']}/4  |  [b\\|M] {s['lbm_count']}/4"
            )
            embed2.add_field(name=field_name, value=field_value, inline=False)

        embed2.set_footer(text=(
            f"Monster cycle synced to GF start | Cycle: 12 days | "
            f"Times auto-localize for each user"
        ))

        print(f"[loot-monster-rotation] Sending 2 embeds ({len(slot_data[:8])} + {len(slot_data[8:])} slots)", flush=True)

        try:
            await interaction.followup.send(embed=embed1)
            print("[loot-monster-rotation] Message 1 sent", flush=True)
        except Exception as e:
            print(f"[loot-monster-rotation] Followup 1 failed: {e}", flush=True)
            try:
                await interaction.response.send_message(embed=embed1)
                print("[loot-monster-rotation] Message 1 sent via send_message", flush=True)
            except Exception as e2:
                print(f"[loot-monster-rotation] send_message 1 also failed: {e2}", flush=True)

        await asyncio.sleep(1)

        try:
            await interaction.followup.send(embed=embed2)
            print("[loot-monster-rotation] Message 2 sent", flush=True)
        except Exception as e:
            print(f"[loot-monster-rotation] Followup 2 failed: {e}", flush=True)

    except Exception as e:
        import traceback
        print(f"[loot-monster-rotation] Processing error: {e}", flush=True)
        traceback.print_exc()
        try:
            await interaction.followup.send(f"Error generating schedule: {str(e)[:200]}", ephemeral=True)
        except Exception:
            try:
                await interaction.response.send_message(f"Error: {str(e)[:200]}", ephemeral=True)
            except Exception as e2:
                print(f"[loot-monster-rotation] Could not send error response: {e2}", flush=True)


@bot.tree.command(name="loot-set-tz", description="Set your personal timezone for bot commands.")
@app_commands.describe(timezone="Your timezone, e.g. IST, EST, PST, Asia/Kolkata, Europe/London")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def gf_set_tz(interaction: discord.Interaction, timezone: str):
    resolved = resolve_timezone(timezone)
    if not resolved:
        await interaction.response.send_message(
            f"❌ Unknown timezone `{timezone}`. Please choose from the autocomplete list or enter a standard timezone (e.g. `EST`, `PST`, `IST`, `UTC`, `Asia/Kolkata`, `Europe/London`).",
            ephemeral=True
        )
        return

    tz_data = load_user_timezones()
    tz_data[str(interaction.user.id)] = resolved
    save_user_timezones(tz_data)

    user_tz_obj = pytz.timezone(resolved)
    current_time_str = datetime.datetime.now(user_tz_obj).strftime("%a %d %b, %I:%M %p")

    await interaction.response.send_message(
        f"✅ Your preferred timezone has been set to **{resolved}**!\n"
        f"🕒 Current time in your timezone: **{current_time_str}**\n"
        f"All commands will now auto-localize for viewers.",
        ephemeral=True
    )


@bot.tree.command(name="loot-my-tz", description="Check your currently configured timezone.")
async def gf_my_tz(interaction: discord.Interaction):
    user_tz_name = get_user_timezone(interaction.user.id)
    if user_tz_name:
        try:
            user_tz_obj = pytz.timezone(user_tz_name)
            current_time_str = datetime.datetime.now(user_tz_obj).strftime("%a %d %b, %I:%M %p")
            await interaction.response.send_message(
                f"🕒 Your configured timezone is **{user_tz_name}**.\n"
                f"• Current time: **{current_time_str}**\n"
                f"• Change it: `/loot-set-tz <timezone>`\n"
                f"• Clear it: `/loot-remove-tz`",
                ephemeral=True
            )
        except Exception:
            await interaction.response.send_message(
                f"🕒 Your configured timezone is `{user_tz_name}`.", ephemeral=True
            )
    else:
        await interaction.response.send_message(
            "ℹ️ You have not set a custom timezone yet! (Discord dynamic timestamps adapt to your device automatically).\n"
            "Use `/loot-set-tz` if you'd like to configure a specific timezone name.",
            ephemeral=True
        )


@bot.tree.command(name="loot-set-tz-user", description="Admin: Set a timezone for another user by mentioning them.")
@app_commands.describe(user="Discord user to set timezone for", timezone="Timezone, e.g. IST, EST, PST, Asia/Kolkata, Europe/London")
@app_commands.autocomplete(timezone=timezone_autocomplete)
async def gf_set_tz_user(interaction: discord.Interaction, user: discord.User, timezone: str):
    resolved = resolve_timezone(timezone)
    if not resolved:
        await interaction.response.send_message(
            f"❌ Unknown timezone `{timezone}`. Please choose from the autocomplete list or enter a standard timezone (e.g. `EST`, `PST`, `IST`, `UTC`, `Asia/Kolkata`, `Europe/London`).",
            ephemeral=True
        )
        return

    if not interaction.guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return

    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ You need Administrator permissions to set other users' timezones.", ephemeral=True)
        return

    tz_data = load_user_timezones()
    tz_data[str(user.id)] = resolved
    save_user_timezones(tz_data)

    target_tz_obj = pytz.timezone(resolved)
    current_time_str = datetime.datetime.now(target_tz_obj).strftime("%a %d %b, %I:%M %p")

    await interaction.response.send_message(
        f"✅ Set **{user.display_name}**'s timezone to **{resolved}**!\n"
        f"🕒 Current time for them: **{current_time_str}**",
        ephemeral=True
    )


@bot.tree.command(name="loot-remove-tz", description="Clear your custom timezone preference.")
async def gf_remove_tz(interaction: discord.Interaction):
    tz_data = load_user_timezones()
    uid = str(interaction.user.id)
    if uid in tz_data:
        removed = tz_data.pop(uid)
        save_user_timezones(tz_data)
        await interaction.response.send_message(
            f" Cleared your custom timezone preference (was {removed}). Default Discord dynamic timestamps will be used.",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "You don't have a custom timezone saved.",
            ephemeral=True
        )


@bot.tree.command(name="loot-scan", description="Scan server nicknames to automatically link Discord IDs to in-game names.")
async def gf_scan(interaction: discord.Interaction):
    await interaction.response.defer()
    if latest_sheet_data is None:
        refresh_scheduler()

    ign_list = []
    if latest_sheet_data and "rosters" in latest_sheet_data:
        for g_dict in latest_sheet_data["rosters"].values():
            for m_list in g_dict.values():
                ign_list.extend(m_list)
    ign_list = list(set(ign_list))

    before_mappings = notifier.load_member_mappings(MAPPINGS_FILE)
    unmapped_before = [ign for ign in ign_list if not before_mappings.get(ign, "").strip().isdigit()]

    if not unmapped_before:
        await interaction.followup.send("✅ All members on the sheet are already mapped to Discord IDs!")
        return

    updated_mappings = auto_match_guild_members(interaction.guild, ign_list)
    matched_now = [ign for ign in unmapped_before if updated_mappings.get(ign, "").strip().isdigit()]

    if matched_now:
        matched_lines = [f"• **{ign}** $\\rightarrow$ <@{updated_mappings[ign]}>" for ign in matched_now]
        await interaction.followup.send(
            f"🎉 **Auto-Scan Complete!** Found and mapped {len(matched_now)} member(s):\n" + "\n".join(matched_lines)
        )
    else:
        still_unmapped = [f"• **{ign}**" for ign in unmapped_before]
        await interaction.followup.send(
            f"⚠️ Could not find exact matching nicknames for:\n" + "\n".join(still_unmapped) +
            "\n\nUse `/loot-map <ign> <@user>` to link a game name to a Discord user!"
        )


@bot.tree.command(name="loot-unregister", description="Remove an in-game name mapping.")
@app_commands.describe(in_game_name="The in-game name to remove from mappings")
async def gf_unregister(interaction: discord.Interaction, in_game_name: str):
    clean_ign = in_game_name.strip()
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)
    if clean_ign in mappings:
        removed_id = mappings.pop(clean_ign)
        notifier.save_member_mappings(mappings, MAPPINGS_FILE)
        # Also remove from locked mappings so it can be re-matched by auto-scan
        locked_igns = notifier.load_locked_igns()
        if clean_ign in locked_igns:
            locked_igns.remove(clean_ign)
            notifier.save_locked_igns(locked_igns)
        await interaction.response.send_message(
            f"✅ Successfully removed registration for **{clean_ign}** (was linked to `{removed_id}`).",
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            f"⚠️ **{clean_ign}** is not currently registered. No changes made.",
            ephemeral=True
        )


@bot.tree.command(name="loot-map", description="Map an in-game name (IGN) to a Discord user for notifications.")
@app_commands.describe(in_game_name="Exact in-game name as listed on the Google Sheet", user="Discord user to ping")
async def gf_map(interaction: discord.Interaction, in_game_name: str, user: discord.User):
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)
    clean_ign = in_game_name.strip()
    old_id = mappings.get(clean_ign, "")
    mappings[clean_ign] = str(user.id)
    notifier.save_member_mappings(mappings, MAPPINGS_FILE)

    locked_igns = notifier.load_locked_igns()
    if clean_ign not in locked_igns:
        locked_igns.append(clean_ign)
        notifier.save_locked_igns(locked_igns)

    if old_id and old_id.isdigit():
        await interaction.response.send_message(
            f"✅ Remapped **{clean_ign}** from `{old_id}` to {user.mention} (ID: `{user.id}`). Locked.",
            ephemeral=False
        )
    else:
        await interaction.response.send_message(
            f"✅ Mapped **{clean_ign}** to {user.mention} (ID: `{user.id}`). Locked.",
            ephemeral=False
        )


@bot.tree.command(name="loot-members", description="List all mapped and unmapped in-game names.")
async def gf_members(interaction: discord.Interaction):
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)
    if not mappings:
        await interaction.response.send_message("No member mappings found. Run `/loot-refresh` first.", ephemeral=True)
        return

    lines = []
    for ign, disc_id in sorted(mappings.items()):
        if disc_id and disc_id.isdigit():
            lines.append(f"• **{ign}** $\\rightarrow$ <@{disc_id}> (`{disc_id}`)")
        else:
            lines.append(f"• **{ign}** $\\rightarrow$ *Not mapped* (will show in bold)")

    embed = discord.Embed(
        title="👥 Member IGN to Discord Mappings",
        description="\n".join(lines),
        color=0xF39C12
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="loot-test", description="Send a test slot notification right now.")
@app_commands.describe(slot_number="Slot number to test (0 to 14)")
async def gf_test(interaction: discord.Interaction, slot_number: int):
    global scheduler
    await interaction.response.defer()
    if scheduler is None:
        await asyncio.to_thread(refresh_scheduler)

    slot_info = scheduler.get_slot_timing(slot_number)
    sheet_data = await get_live_sheet_data(force=True)
    rosters = sheet_data.get("rosters", {})
    mappings = notifier.load_member_mappings(MAPPINGS_FILE)

    bm = rosters.get("BM", {}).get(slot_number, [])
    lbm = rosters.get("bM", {}).get(slot_number, [])

    payload = notifier.build_slot_alert_payload(
        "START", slot_info, bm, lbm, mappings,
        user_timezones=notifier.load_user_timezones(),
        user_tz_name=get_user_timezone(interaction.user.id)
    )
    embed = discord.Embed.from_dict(payload["embeds"][0])
    await interaction.followup.send(content=f"🧪 **Test Output**:\n{payload['content']}", embed=embed)


@bot.tree.command(name="loot-refresh", description="Immediately re-sync with the live Google Sheet.")
async def gf_refresh(interaction: discord.Interaction):
    await interaction.response.defer()
    await asyncio.to_thread(refresh_scheduler)
    await get_live_sheet_data(force=True)
    await interaction.followup.send("🔄 Google Sheet re-fetched and slot schedules refreshed!")


@bot.tree.command(name="loot-set-start", description="Set or override the Guild Fest start date.")
@app_commands.describe(date_str="Start date in YYYY-MM-DD format (e.g. 2026-09-06)")
async def gf_set_start(interaction: discord.Interaction, date_str: str):
    global scheduler
    try:
        parts = [int(p) for p in date_str.strip().split("-")]
        new_date = datetime.date(parts[0], parts[1], parts[2])
        slot_0_dt = compute_slot_0_utc(new_date)

        cfg = load_config()
        cfg["fallback_start_date"] = date_str
        save_config(cfg)

        sheet_data = latest_sheet_data or {}
        rosters = sheet_data.get("rosters", {})
        all_slot_nums = list(rosters.get("BM", {}).keys()) + list(rosters.get("bM", {}).keys())
        total_slots = (max(all_slot_nums) + 1) if all_slot_nums else cfg.get("total_slots", 15)

        scheduler = GFScheduler(slot_0_start_dt=slot_0_dt, total_slots=total_slots)
        user_tz_name = get_user_timezone(interaction.user.id)
        user_tz = pytz.timezone(user_tz_name) if user_tz_name else None
        user_start_line = f"\nYour local time: **<t:{int(slot_0_dt.timestamp())}:F>**" if user_tz_name else ""

        await interaction.response.send_message(
            f"✅ Guild Fest start date updated!\n"
            f"Slot 0 starts on **<t:{int(slot_0_dt.timestamp())}:F>** (<t:{int(slot_0_dt.timestamp())}:R>)."
            f"{user_start_line}"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Error setting date: {e}", ephemeral=True)


def main():
    cfg = load_config()
    token = cfg.get("discord_bot_token", "").strip()
    if not token:
        print("[!] No 'discord_bot_token' found in config.json.")
        print("[!] Please enter your bot token in config.json to run the Discord Bot.")
        print("[!] Alternatively, you can run 'python webhook_runner.py' to use Discord Webhooks!")
        return

    print("Starting Lords Mobile GF Discord Bot...")
    bot.run(token)


if __name__ == "__main__":
    main()
