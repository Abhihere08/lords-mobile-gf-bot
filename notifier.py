"""
Discord Notifier & Embed Builder for Lords Mobile Guild Fest (GF).
Resolves In-Game Names (IGNs) to Discord <@ID> mentions with case-insensitive
and fuzzy normalization matching.
"""

import os
import sys
import json
import re
import difflib
import datetime
from collections import Counter
from typing import Dict, List, Optional, Tuple, Any
import pytz
import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_MAPPINGS_FILE = "member_mappings.json"
DEFAULT_USER_TZ_FILE = "user_timezones.json"


def load_user_timezones(tz_file: str = DEFAULT_USER_TZ_FILE) -> Dict[str, str]:
    """Loads Discord User ID -> Timezone string mapping."""
    if os.path.exists(tz_file):
        try:
            with open(tz_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading user timezones: {e}")
            return {}
    return {}


def get_user_timezone(user_id: int) -> Optional[str]:
    """Returns user's timezone string if set, else None."""
    data = load_user_timezones()
    return data.get(str(user_id))


def normalize_name(name: str) -> str:
    """Strips guild tags like [B|M], (R4), and non-alphanumeric chars for clean matching."""
    if not name:
        return ""
    cleaned = re.sub(r"\[.*?\]|\(.*?\)", "", name)
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", cleaned)
    return cleaned.lower()


def load_member_mappings(mappings_file: str = DEFAULT_MAPPINGS_FILE) -> Dict[str, str]:
    """Loads IGN -> Discord User ID mapping."""
    if os.path.exists(mappings_file):
        try:
            with open(mappings_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading member mappings: {e}")
            return {}
    return {}


def save_member_mappings(mappings: Dict[str, str], mappings_file: str = DEFAULT_MAPPINGS_FILE):
    """Saves updated mappings to JSON."""
    try:
        with open(mappings_file, "w", encoding="utf-8") as f:
            json.dump(mappings, f, indent=2)
    except Exception as e:
        print(f"Error saving member mappings: {e}")


def load_locked_igns(locked_file: str = "locked_mappings.json") -> List[str]:
    """Loads the list of locked IGNs that should never be auto-rematched."""
    if os.path.exists(locked_file):
        try:
            with open(locked_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                if isinstance(data, dict) and "locked" in data:
                    return data["locked"]
        except Exception:
            pass
    return []


def save_locked_igns(locked_igns: List[str], locked_file: str = "locked_mappings.json"):
    """Saves the list of locked IGNs."""
    try:
        with open(locked_file, "w", encoding="utf-8") as f:
            json.dump(locked_igns, f, indent=2)
    except Exception as e:
        print(f"Error saving locked mappings: {e}")


def resolve_discord_id(ign: str, mappings: Dict[str, str]) -> Optional[str]:
    """
    Resolves an in-game name to a Discord User ID using:
    1. Exact match
    2. Case-insensitive match (e.g. 'CHAOTIC LIES' == 'chaotic lies')
    3. Normalized match (stripping brackets [B|M], punctuation, extra spaces)
    4. Fuzzy match (>= 85% similarity, e.g. typo 'chotic lies' -> 'chaotic lies')
    """
    if not ign or not mappings:
        return None

    clean_ign = ign.strip()

    # 1. Exact match
    if clean_ign in mappings and mappings[clean_ign].strip().isdigit():
        return mappings[clean_ign].strip()

    # 2. Case-insensitive match
    ign_lower = clean_ign.lower()
    for k, v in mappings.items():
        if k.strip().lower() == ign_lower and v.strip().isdigit():
            return v.strip()

    # 3. Normalized match
    norm_ign = normalize_name(clean_ign)
    if not norm_ign:
        return None

    for k, v in mappings.items():
        if normalize_name(k) == norm_ign and v.strip().isdigit():
            return v.strip()

    # 4. Fuzzy match (catches typos like 'chotic lies' vs 'chaotic lies')
    best_id = None
    best_score = 0.0
    for k, v in mappings.items():
        if not v.strip().isdigit():
            continue
        norm_k = normalize_name(k)
        if not norm_k:
            continue
        score = difflib.SequenceMatcher(None, norm_ign, norm_k).ratio()
        if score > best_score and score >= 0.85:
            best_score = score
            best_id = v.strip()

    return best_id


def format_member_display(
    ign: str,
    count: int,
    mappings: Dict[str, str],
    user_timezones: Optional[Dict[str, str]] = None,
    slot_start_dt: Optional[datetime.datetime] = None
) -> Tuple[str, Optional[str]]:
    """
    Returns (display_str, discord_ping_id_or_none).
    If mapped to a valid Discord ID, produces <@USER_ID>.
    If the hunter configured a timezone, shows their local start time badge [e.g. 10:30 PM EST].
    """
    discord_id = resolve_discord_id(ign, mappings)
    count_suffix = f" *(x{count} hunts)*" if count > 1 else ""

    tz_badge = ""
    if user_timezones and slot_start_dt and discord_id and discord_id in user_timezones:
        try:
            tz_obj = pytz.timezone(user_timezones[discord_id])
            local_dt = slot_start_dt.astimezone(tz_obj)
            tz_badge = f" `[{local_dt.strftime('%I:%M %p')}]`"
        except Exception:
            pass

    if discord_id and discord_id.isdigit():
        mention = f"<@{discord_id}>"
        return f"{mention}{tz_badge}{count_suffix}", discord_id
    else:
        return f"**{ign}**{tz_badge}{count_suffix}", None


def format_guild_section(
    members: List[str],
    mappings: Dict[str, str],
    max_spots: int = 4,
    user_timezones: Optional[Dict[str, str]] = None,
    slot_start_dt: Optional[datetime.datetime] = None
) -> Tuple[str, List[str]]:
    """
    Formats the list of hunters for a guild section and returns (formatted_text, ping_ids).
    """
    if not members:
        return "⚠️ *No members signed up! (4 open spots)*", []

    counts = Counter(members)
    lines = []
    pings = []

    for ign, cnt in counts.items():
        display_str, ping_id = format_member_display(ign, cnt, mappings, user_timezones, slot_start_dt)
        lines.append(f"• {display_str}")
        if ping_id:
            pings.append(f"<@{ping_id}>")

    total_taken = len(members)
    open_spots = max_spots - total_taken
    if open_spots > 0:
        lines.append(f"⚠️ *{open_spots} open spot(s) remaining!*")

    return "\n".join(lines), pings


def build_slot_alert_payload(
    alert_type: str,
    slot_info: Dict[str, Any],
    bm_members: List[str],
    little_bm_members: List[str],
    mappings: Dict[str, str],
    user_timezones: Optional[Dict[str, str]] = None,
    user_tz_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constructs Discord message payload with embed and mention pings in the outer content.
    """
    if user_timezones is None:
        user_timezones = load_user_timezones()

    slot_num = slot_info["slot_num"]
    start_ts = slot_info.get("start_ts") or int(slot_info["start_ist"].timestamp())
    end_ts = slot_info.get("end_ts") or int(slot_info["end_ist"].timestamp())
    start_dt = slot_info.get("start_ist")

    bm_text, bm_pings = format_guild_section(bm_members, mappings, max_spots=4, user_timezones=user_timezones, slot_start_dt=start_dt)
    lbm_text, lbm_pings = format_guild_section(little_bm_members, mappings, max_spots=4, user_timezones=user_timezones, slot_start_dt=start_dt)

    all_pings = list(set(bm_pings + lbm_pings))
    mention_header = " ".join(all_pings) if all_pings else ""

    if alert_type == "START":
        if slot_num == 0:
            title = f"⚔️ Guild Fest Slot {slot_num} is live, hunt begins after 8 hr take your quest and be ready for slot 1 ⚔️"
        else:
            title = f"⚔️ Guild Fest Slot {slot_num} is NOW LIVE! ⚔️"
        color = 0x00FF88  # Bright Green / Emerald
        description = (
            f"The new 8-hour Guild Fest loot slot has started!\n"
            f"Ends <t:{end_ts}:R> at **<t:{end_ts}:t>**.\n"
            f"Please take your legendary loot quests and meet your requirements."
        )
        content = f"🔔 **SLOT {slot_num} LIVE ALERT** {mention_header}".strip()
    elif alert_type == "REMINDER":
        title = f"⏳ Slot {slot_num} Starting in 15 Minutes!"
        color = 0xFFA500  # Orange / Amber
        description = (
            f"Slot {slot_num} starts <t:{start_ts}:R> at **<t:{start_ts}:t>**!\n"
            f"Assigned members, please prepare your heroes and speedups!"
        )
        content = f"⚠️ **SLOT {slot_num} 15-MIN WARNING** {mention_header}".strip()
    else:
        title = f"Guild Fest Slot {slot_num} Update"
        color = 0x3498DB
        description = ""
        content = mention_header

    # Format Time Window in user's timezone if available
    if user_tz_name:
        try:
            time_window = f"**Your Timezone: {user_tz_name}**\n*<t:{start_ts}:f> → <t:{end_ts}:t>*"
        except Exception:
            time_window = f"**<t:{start_ts}:f> → <t:{end_ts}:t>** (<t:{end_ts}:R>)"
    else:
        time_window = f"**<t:{start_ts}:f> → <t:{end_ts}:t>** (<t:{end_ts}:R>)"

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": [
            {
                "name": "⏰ Time Window (Your Local Time)",
                "value": time_window,
                "inline": False
            },
            {
                "name": f"👑 [B|M] Blood Mafia ({len(bm_members)}/4)",
                "value": bm_text,
                "inline": True
            },
            {
                "name": f"🛡️ [b|M] Little Blood Mafia ({len(little_bm_members)}/4)",
                "value": lbm_text,
                "inline": True
            },
            {
                "name": "📜 Legendary Loot Quest Targets",
                "value": (
                    "• **200% Loot**: 448 pts (7 quests = 3,136 pts)\n"
                    "• **120% Loot**: 268 pts (7 quests = 1,876 pts)\n"
                    "• **Target**: BIG BM 5K | Little bM 4K pts mandatory"
                ),
                "inline": False
            }
        ],
        "footer": {
            "text": f"Blood Mafia GF Bot • Consecutive 8h Slots • Auto-Synced with Google Sheets"
        }
    }

    return {
        "content": content,
        "embeds": [embed]
    }


def send_discord_webhook(webhook_url: str, payload: Dict[str, Any]) -> bool:
    """Sends payload to a Discord webhook."""
    if not webhook_url or not webhook_url.startswith("http"):
        print("Invalid webhook URL provided.")
        return False

    try:
        res = requests.post(webhook_url, json=payload, timeout=10)
        if res.status_code in (200, 204):
            return True
        else:
            print(f"Webhook failed with status {res.status_code}: {res.text}")
            return False
    except Exception as e:
        print(f"Error sending webhook: {e}")
        return False
