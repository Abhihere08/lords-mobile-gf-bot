"""
Monster Schedule Module for Lords Mobile GF Bot.
Fixed 12-day monster rotation (never changes).
"""

import datetime
from typing import Dict, List, Optional, Any

# Fixed 12-day monster rotation from lordstools.com (never changes)
MONSTER_ROTATION = [
    {"day": 1, "monsters": [{"slug": "frostwing", "name": "Frostwing"}, {"slug": "blackwing", "name": "Blackwing"}]},
    {"day": 2, "monsters": [{"slug": "cottageroar", "name": "Cottageroar"}, {"slug": "serpent-gladiator", "name": "Serpent Gladiator"}]},
    {"day": 3, "monsters": [{"slug": "gargantua", "name": "Gargantua"}, {"slug": "hardrox", "name": "Hardrox"}]},
    {"day": 4, "monsters": [{"slug": "jade-wyrm", "name": "Jade Wyrm"}, {"slug": "grim-reaper", "name": "Grim Reaper"}]},
    {"day": 5, "monsters": [{"slug": "hell-drider", "name": "Hell Drider"}, {"slug": "snow-beast", "name": "Snow Beast"}]},
    {"day": 6, "monsters": [{"slug": "hootclaw", "name": "Hootclaw"}, {"slug": "arctic-flipper", "name": "Arctic Flipper"}]},
    {"day": 7, "monsters": [{"slug": "queen-bee", "name": "Queen Bee"}, {"slug": "mega-maggot", "name": "Mega Maggot"}]},
    {"day": 8, "monsters": [{"slug": "mecha-trojan", "name": "Mecha Trojan"}, {"slug": "voodoo-shaman", "name": "Voodoo Shaman"}]},
    {"day": 9, "monsters": [{"slug": "saberfang", "name": "Saberfang"}, {"slug": "gryphon", "name": "Gryphon"}]},
    {"day": 10, "monsters": [{"slug": "gawrilla", "name": "Gawrilla"}, {"slug": "necrosis", "name": "Necrosis"}]},
    {"day": 11, "monsters": [{"slug": "bon-appeti", "name": "Bon Appeti"}, {"slug": "noceros", "name": "Noceros"}]},
    {"day": 12, "monsters": [{"slug": "terrorthorn", "name": "Terrorthorn"}, {"slug": "tidal-titan", "name": "Tidal Titan"}]},
]

# Website rotation anchor (date) for 12-day cycle
WEBSITE_ANCHOR_DATE = datetime.date(2026, 7, 19)
CYCLE_DAYS = 12


def get_day_index_for_date(d: datetime.date) -> int:
    """Returns day index (0-11) in the 12-day rotation for a given date."""
    days_diff = (d - WEBSITE_ANCHOR_DATE).days
    return days_diff % CYCLE_DAYS


def get_monsters_for_day_index(day_idx: int) -> List[Dict[str, str]]:
    """Returns monsters for a given 0-based day index in the rotation."""
    return MONSTER_ROTATION[day_idx % CYCLE_DAYS]["monsters"]


def get_monster_schedule() -> Dict[str, Any]:
    """Returns the static monster rotation data."""
    return {
        "days": MONSTER_ROTATION,
        "cycleDays": CYCLE_DAYS,
        "anchor": {"date": WEBSITE_ANCHOR_DATE.isoformat()},
    }


# Legacy helpers (kept for compatibility)
def get_rotation_day_index() -> int:
    return get_day_index_for_date(datetime.datetime.now(datetime.timezone.utc).date())


def get_today_monsters(schedule: Dict[str, Any] = None) -> List[Dict[str, str]]:
    return get_monsters_for_day_index(get_rotation_day_index())