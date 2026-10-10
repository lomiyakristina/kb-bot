"""Мини-приложение: тариф, подпись Telegram, просмотр без записи в базу."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from aiohttp.test_utils import TestClient, TestServer

from logic import booking_days, open_slots
from storage import Storage
from webapp import build_app, build_catalog, check_init_data, quote

MSK = ZoneInfo("Europe/Moscow")


def sign(token: str, fields: dict) -> str:
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()


class WebappTests(unittest.IsolatedAsyncioTestCase):
    def test_saturday_nearest_is_5700(self) -> None:
        now = datetime(2026, 10, 10, 14, 14, tzinfo=MSK)
        catalog = build_catalog(now)
        self.assertEqual(catalog["nearest"]["price"], 5700)
        self.assertEqual(catalog["nearest"]["start"], "15:00")
        self.assertIn("14:30", catalog["brief"][-1])

    def test_quote_counts_adults_and_rejects_junk(self) -> None:
        now = datetime(2026, 10, 12, 9, 0, tzinfo=MSK)
        day = booking_days(now)[0]
        slot = open_slots(day, now)[0]
        quoted = quote(
            {
                "hall": "female",
                "offer": "ticket",
                "date": day.isoformat(),
                "start": slot.start,
                "guests": 2,
                "extra": "none",
                "name": "Анна",
                "phone": "8 925 000-00-00",
            },
            now,
        )
        self.assertEqual(quoted["price_each"], 4500)
        self.assertIn("9 000", quoted["estimate"])
        with self.assertRaises(Exception):
            quote({**{"hall": "female", "offer": "ticket", "date": day.isoformat(), "start": slot.start, "guests": 2, "extra": "none", "name": "Анна", "phone": "123"}}, now)

    def test_vip_room_is_flat_and_capped(self) -> None:
        now = datetime(2026, 10, 12, 9, 0, tzinfo=MSK)
        day = booking_days(now, hours=3, fixed_price=9000)[0]
        slot = open_slots(day, now, hours=3, fixed_price=9000)[0]
        payload = {
            "hall": "female",
            "offer": "vip",
            "date": day.isoformat(),
            "start": slot.start,
            "guests": 4,
            "extra": "none",
            "name": "Анна",
            "phone": "89250000000",
        }
        quoted = quote(payload, now)
        self.assertEqual(quoted["price_each"], 9000)
        self.assertEqual(quoted["price_flat"], 1)
        self.assertIn("Комната", quoted["estimate"])
        payload["guests"] = 5
        with self.assertRaises(Exception):
            quote(payload, now)

    def test_init_data_signature(self) -> None:
        now = datetime(2026, 10, 10, 15, 0, tzinfo=MSK)
        token = "123456:test-token"
        fields = {
            "auth_date": str(int(now.timestamp())),
            "query_id": "abc",
            "user": json.dumps({"id": 42, "first_name": "Анна"}, ensure_ascii=False, separators=(",", ":")),
        }
        fields["hash"] = sign(token, {key: value for key, value in fields.items()})
        init_data = urlencode(fields)
        user = check_init_data(init_data, token, now)
        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user["id"], 42)
        fields["hash"] = "0" * 64
        self.assertIsNone(check_init_data(urlencode(fields), token, now))

    async def test_preview_does_not_write_booking(self) -> None:
        os.environ.pop("WEBAPP_URL", None)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = Storage(Path(folder.name) / "preview.sqlite")
        app = build_app(None, storage, set())
        now = datetime(2026, 10, 12, 9, 0, tzinfo=MSK)
        day = booking_days(now)[0]
        slot = open_slots(day, now)[0]
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/api/booking",
                json={
                    "hall": "male",
                    "offer": "ticket",
                    "date": day.isoformat(),
                    "start": slot.start,
                    "guests": 1,
                    "extra": "none",
                    "name": "Иван",
                    "phone": "89250000000",
                },
            )
            body = await response.json()
        self.assertEqual(response.status, 200)
        self.assertTrue(body["preview"])
        self.assertIn("не ушла", body["message"])
        self.assertEqual(storage.pending_count(0), 0)
        storage.close()


if __name__ == "__main__":
    unittest.main()
