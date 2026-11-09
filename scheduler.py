"""
Scheduler engine for Lords Mobile Guild Fest (GF) slots.
Fixed reset: Slot 0 starts at 05:00 UTC on (PST header date + 1 day).
Each slot is 8 hours. UI uses Discord dynamic timestamps (local time per viewer).
"""

import os
import json
import datetime
from typing import Dict, List, Optional, Any
import pytz

IST = pytz.timezone("Asia/Kolkata")
PST = pytz.timezone("America/Los_Angeles")
UTC = pytz.utc

DEFAULT_SLOT_COUNT = 15
SLOT_HOURS = 8
RESET_HOUR_UTC = 5  # 05:00 UTC fixed game reset


def compute_slot_0_utc(sheet_date_pst: datetime.date) -> datetime.datetime:
    """
    Computes Slot 0 start in UTC.
    Header date is PST; Slot 0 starts at 05:00 UTC on (PST header date + 1 day).
    Example: PST header 2026-11-08 -> 2026-11-09 05:00:00 UTC
    """
    start_date = sheet_date_pst + datetime.timedelta(days=1)
    return UTC.localize(datetime.datetime(start_date.year, start_date.month, start_date.day, RESET_HOUR_UTC, 0))


# Backward-compatible alias (returns UTC now, despite the name)
def compute_slot_0_ist(sheet_date: datetime.date, date_is_pst_reset: bool = True,
                       hour: int = 10, minute: int = 30) -> datetime.datetime:
    return compute_slot_0_utc(sheet_date)


class GFScheduler:
    def __init__(
        self,
        slot_0_start_dt: Optional[datetime.datetime] = None,
        total_slots: int = DEFAULT_SLOT_COUNT,
        reminder_minutes: int = 15,
        state_file: str = "sent_alerts.json",
        slot_times: Optional[Dict[int, Dict[str, Any]]] = None,  # ignored
        base_date: Optional[datetime.date] = None,  # ignored
    ):
        self.total_slots = total_slots
        self.reminder_minutes = reminder_minutes
        self.state_file = state_file
        self.sent_alerts = self._load_sent_alerts()

        if slot_0_start_dt is not None:
            if slot_0_start_dt.tzinfo is None:
                self.slot_0_start = UTC.localize(slot_0_start_dt)
            else:
                self.slot_0_start = slot_0_start_dt.astimezone(UTC)
        else:
            self.slot_0_start = UTC.localize(datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))

    @property
    def slot_0_start_utc(self) -> datetime.datetime:
        return self.slot_0_start.astimezone(UTC)

    @property
    def slot_0_start_ist(self) -> datetime.datetime:
        return self.slot_0_start.astimezone(IST)

    def _load_sent_alerts(self) -> Dict[str, Any]:
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_sent_alerts(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.sent_alerts, f, indent=2)
        except Exception as e:
            print(f"Error saving alert state: {e}")

    def get_event_key(self) -> str:
        return self.slot_0_start_utc.strftime("%Y-%m-%d")

    def get_slot_timing(self, slot_num: int) -> Dict[str, Any]:
        """Fixed 8-hour slots from 05:00 UTC reset."""
        start_utc = self.slot_0_start_utc + datetime.timedelta(hours=slot_num * SLOT_HOURS)
        end_utc = start_utc + datetime.timedelta(hours=SLOT_HOURS)

        start_ist = start_utc.astimezone(IST)
        end_ist = end_utc.astimezone(IST)
        start_pst = start_utc.astimezone(PST)
        end_pst = end_utc.astimezone(PST)

        start_date_str = start_ist.strftime('%a %d %b')
        end_date_str = end_ist.strftime('%a %d %b')
        if start_date_str == end_date_str:
            fmt_ist = f"{start_ist.strftime('%d %b')}  {start_ist.strftime('%I:%M %p')} → {end_ist.strftime('%I:%M %p')} IST"
        else:
            fmt_ist = f"{start_ist.strftime('%d %b %I:%M %p')} → {end_ist.strftime('%d %b %I:%M %p')} IST"

        start_pst_date = start_pst.strftime('%a %d %b')
        end_pst_date = end_pst.strftime('%a %d %b')
        if start_pst_date == end_pst_date:
            fmt_pst = f"{start_pst.strftime('%d %b')}  {start_pst.strftime('%I:%M %p')} → {end_pst.strftime('%I:%M %p')} PST"
        else:
            fmt_pst = f"{start_pst.strftime('%d %b %I:%M %p')} → {end_pst.strftime('%d %b %I:%M %p')} PST"

        return {
            "slot_num": slot_num,
            "start_utc": start_utc,
            "end_utc": end_utc,
            "start_ist": start_ist,
            "end_ist": end_ist,
            "start_pst": start_pst,
            "end_pst": end_pst,
            "start_ts": int(start_utc.timestamp()),
            "end_ts": int(end_utc.timestamp()),
            "formatted_ist": fmt_ist,
            "formatted_pst": fmt_pst,
        }

    def get_all_slots(self) -> List[Dict[str, Any]]:
        return [self.get_slot_timing(i) for i in range(self.total_slots)]

    def get_active_slot(self, now: Optional[datetime.datetime] = None) -> Optional[Dict[str, Any]]:
        if now is None:
            now = datetime.datetime.now(UTC)
        elif now.tzinfo is None:
            now = UTC.localize(now)
        else:
            now = now.astimezone(UTC)

        for slot in self.get_all_slots():
            if slot["start_utc"] <= now < slot["end_utc"]:
                remaining = slot["end_utc"] - now
                slot_info = dict(slot)
                slot_info["remaining_seconds"] = int(remaining.total_seconds())
                slot_info["remaining_formatted"] = self._format_timedelta(remaining)
                return slot_info
        return None

    def get_next_slot(self, now: Optional[datetime.datetime] = None) -> Optional[Dict[str, Any]]:
        if now is None:
            now = datetime.datetime.now(UTC)
        elif now.tzinfo is None:
            now = UTC.localize(now)
        else:
            now = now.astimezone(UTC)

        for slot in self.get_all_slots():
            if now < slot["start_utc"]:
                time_until = slot["start_utc"] - now
                slot_info = dict(slot)
                slot_info["until_start_seconds"] = int(time_until.total_seconds())
                slot_info["until_start_formatted"] = self._format_timedelta(time_until)
                return slot_info
        return None

    def check_pending_alerts(self, now: Optional[datetime.datetime] = None) -> List[Dict[str, Any]]:
        if now is None:
            now = datetime.datetime.now(UTC)
        elif now.tzinfo is None:
            now = UTC.localize(now)
        else:
            now = now.astimezone(UTC)

        event_key = self.get_event_key()
        if event_key not in self.sent_alerts:
            self.sent_alerts[event_key] = {}

        alerts_to_send = []
        for slot in self.get_all_slots():
            slot_num = slot["slot_num"]
            slot_key = f"slot_{slot_num}"
            if slot_key not in self.sent_alerts[event_key]:
                self.sent_alerts[event_key][slot_key] = {"reminder": False, "start": False}

            status = self.sent_alerts[event_key][slot_key]

            if self.reminder_minutes > 0 and not status.get("reminder"):
                reminder_time = slot["start_utc"] - datetime.timedelta(minutes=self.reminder_minutes)
                if reminder_time <= now < slot["start_utc"]:
                    alerts_to_send.append({"type": "REMINDER", "slot_num": slot_num, "slot_timing": slot})

            if not status.get("start"):
                trigger_window_end = slot["start_utc"] + datetime.timedelta(minutes=15)
                if slot["start_utc"] <= now < trigger_window_end:
                    alerts_to_send.append({"type": "START", "slot_num": slot_num, "slot_timing": slot})

        return alerts_to_send

    def mark_alert_sent(self, alert_type: str, slot_num: int):
        event_key = self.get_event_key()
        if event_key not in self.sent_alerts:
            self.sent_alerts[event_key] = {}
        slot_key = f"slot_{slot_num}"
        if slot_key not in self.sent_alerts[event_key]:
            self.sent_alerts[event_key][slot_key] = {}

        if alert_type == "REMINDER":
            self.sent_alerts[event_key][slot_key]["reminder"] = True
        elif alert_type == "START":
            self.sent_alerts[event_key][slot_key]["start"] = True

        self._save_sent_alerts()

    @staticmethod
    def _format_timedelta(td: datetime.timedelta) -> str:
        total_seconds = int(td.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m {seconds}s"


if __name__ == "__main__":
    # Test: PST header 2026-11-08 -> Slot 0 at 2026-11-09 05:00:00 UTC
    slot_0 = compute_slot_0_utc(datetime.date(2026, 11, 8))
    sched = GFScheduler(slot_0)
    print(f"Slot 0 UTC: {slot_0}")
    for s in sched.get_all_slots()[:5]:
        print(f"Slot {s['slot_num']}: {s['start_utc']} -> {s['end_utc']} (ts {s['start_ts']}->{s['end_ts']})")