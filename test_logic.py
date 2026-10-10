"""Проверки тарифа, телефона, званий и заявок. Telegram не нужен."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from logic import (
    booking_days,
    clean_name,
    coals_phrase,
    format_phone,
    host_brief,
    money,
    nearest_entry,
    next_steam,
    normalize_phone,
    open_slots,
    progress_bar,
    rank_for,
    slots_for,
)
from storage import Storage

MSK = ZoneInfo("Europe/Moscow")


class LogicTests(unittest.TestCase):
    def test_weekday_morning_is_4500(self) -> None:
        monday = datetime(2026, 10, 5, 9, 0, tzinfo=MSK)
        slots = slots_for(monday.date())
        self.assertEqual(slots[0].start, "09:00")
        self.assertEqual(slots[0].end, "13:00")
        self.assertEqual(slots[0].price, 4500)
        afternoon = next(slot for slot in slots if slot.start == "14:00")
        self.assertEqual(afternoon.price, 5700)
        self.assertEqual(afternoon.end, "18:00")

    def test_weekend_is_5700(self) -> None:
        saturday = datetime(2026, 10, 10, 9, 0, tzinfo=MSK).date()
        prices = {slot.price for slot in slots_for(saturday)}
        self.assertEqual(prices, {5700})

    def test_today_hides_started_windows(self) -> None:
        now = datetime(2026, 10, 5, 13, 30, tzinfo=MSK)
        labels = [slot.start for slot in open_slots(now.date(), now)]
        self.assertEqual(labels, ["14:00", "15:00", "16:00", "17:00", "18:00"])

    def test_next_steam_and_host(self) -> None:
        morning = datetime(2026, 10, 5, 9, 40, tzinfo=MSK)
        self.assertEqual(next_steam(morning), (morning.date(), "10:00"))
        brief = host_brief(morning)
        self.assertIn("4 500", brief)
        self.assertIn("1 500", brief)
        self.assertIn("10:00", brief)
        evening = datetime(2026, 10, 5, 22, 30, tzinfo=MSK)
        self.assertEqual(next_steam(evening)[1], "10:00")
        self.assertIn("завтра", host_brief(evening))
        day, slot = nearest_entry(morning)
        self.assertEqual(day, morning.date())
        self.assertEqual(slot.start, "10:00")
        self.assertEqual(slot.price, 4500)

    def test_late_evening_starts_tomorrow(self) -> None:
        now = datetime(2026, 10, 5, 22, 10, tzinfo=MSK)
        days = booking_days(now, horizon=2)
        self.assertEqual(days[0].isoformat(), "2026-10-06")

    def test_phone(self) -> None:
        self.assertEqual(normalize_phone("8 (925) 105-77-77"), "+79251057777")
        self.assertEqual(normalize_phone("9251057777"), "+79251057777")
        self.assertIsNone(normalize_phone("123"))
        self.assertEqual(format_phone("+79251057777"), "+7 925 105-77-77")

    def test_ranks_and_money(self) -> None:
        self.assertEqual(rank_for(0)[0], "Искра")
        self.assertEqual(rank_for(90)[0], "Жар")
        self.assertEqual(rank_for(320)[0], "Хранитель")
        self.assertEqual(rank_for(320)[2], None)
        self.assertIn("█", progress_bar(50))
        self.assertEqual(money(4500), "4 500 ₽")
        self.assertEqual(coals_phrase(4), "+4 уголька")
        self.assertEqual(coals_phrase(12), "+12 угольков")
        self.assertIsNone(clean_name("<script>"))
        self.assertEqual(clean_name("  Анна  "), "Анна")


class StorageTests(unittest.TestCase):
    def test_booking_confirm_and_miss(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db = Storage(Path(folder) / "t.sqlite")
            db.ensure_user(7, "guest", "Анна")
            self.assertIn("Первый заход", " ".join(db.note_start(7)))
            self.assertEqual(db.note_start(7), [])
            booking_id = db.create_booking(
                {
                    "user_id": 7,
                    "hall": "female",
                    "visit_date": "2026-10-06",
                    "slot_label": "13:00–16:00",
                    "guests": 2,
                    "guest_name": "Анна",
                    "phone": "+79251057777",
                    "price_each": 3000,
                    "rank_title": "Искра",
                }
            )
            self.assertEqual(db.user(7)["coals"], 8 + 12)
            self.assertIn("table", db.achievements(7))
            db.set_status(booking_id, "confirmed")
            self.assertEqual(db.user(7)["visits"], 1)
            self.assertEqual(db.user(7)["coals"], 8 + 12 + 40)
            db.set_status(booking_id, "missed")
            self.assertEqual(db.user(7)["visits"], 0)
            self.assertEqual(db.user(7)["coals"], 8 + 12)
            self.assertFalse(db.join_waitlist(7, "spa") is False)
            self.assertFalse(db.join_waitlist(7, "spa"))
            db.ensure_user(9, "guest", "Гость Тест")
            first, row = db.mark_start(9, "instagram")
            self.assertTrue(first)
            self.assertEqual(int(row["start_count"]), 1)
            self.assertEqual(row["source"], "instagram")
            again, row = db.mark_start(9, "vk")
            self.assertFalse(again)
            self.assertEqual(int(row["start_count"]), 2)
            self.assertEqual(row["source"], "instagram")
            total, rows = db.starts()
            self.assertEqual(total, 1)
            self.assertEqual(rows[0]["user_id"], 9)
            db.ensure_user(11, "plain", "Без Метки")
            db.mark_start(11)
            self.assertIsNone(db.user(11)["source"])
            db.close()


class HallPhotoTests(unittest.TestCase):
    def test_male_hall_photos_are_on_disk(self) -> None:
        from content import HALLS

        names = HALLS["male"]["photos"]
        self.assertEqual(len(names), 7)
        root = Path(__file__).resolve().parent / "photos"
        for name in names:
            path = root / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
