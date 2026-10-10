"""SQLite: гости, заявки, знаки, лист ожидания."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock

from content import ACHIEVEMENTS
from logic import coals_phrase

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "zhar.sqlite"

REQUEST_COALS = 12
VISIT_COALS = 40
PENDING_LIMIT = 3


class Storage:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                coals INTEGER NOT NULL DEFAULT 0,
                visits INTEGER NOT NULL DEFAULT 0,
                ritual_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                ritual_day TEXT,
                schedule_day TEXT,
                saw_tariffs INTEGER NOT NULL DEFAULT 0,
                saw_male INTEGER NOT NULL DEFAULT 0,
                saw_female INTEGER NOT NULL DEFAULT 0,
                got_start INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS achievements (
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                earned_at TEXT NOT NULL,
                PRIMARY KEY (user_id, code)
            );
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                hall TEXT NOT NULL,
                visit_date TEXT NOT NULL,
                slot_label TEXT NOT NULL,
                guests INTEGER NOT NULL,
                guest_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                price_each INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                rank_title TEXT NOT NULL,
                request_coals INTEGER NOT NULL DEFAULT 0,
                visit_coals INTEGER NOT NULL DEFAULT 0,
                price_flat INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS waitlist (
                user_id INTEGER NOT NULL,
                space TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, space)
            );
            """
        )
        self._conn.commit()
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(bookings)")}
        if "price_flat" not in columns:
            self._conn.execute("ALTER TABLE bookings ADD COLUMN price_flat INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def ensure_user(self, user_id: int, username: str | None, full_name: str) -> sqlite3.Row:
        with self._lock:
            row = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            if row:
                self._conn.execute(
                    "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
                    (username, full_name, user_id),
                )
                self._conn.commit()
                return self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
            self._conn.execute(
                "INSERT INTO users (user_id, username, full_name, created_at) VALUES (?, ?, ?, ?)",
                (user_id, username, full_name, _now()),
            )
            self._conn.commit()
            return self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

    def user(self, user_id: int) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if row is None:
            raise KeyError(user_id)
        return row

    def achievements(self, user_id: int) -> set[str]:
        rows = self._conn.execute("SELECT code FROM achievements WHERE user_id = ?", (user_id,)).fetchall()
        return {row["code"] for row in rows}

    def pending_count(self, user_id: int) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM bookings WHERE user_id = ? AND status = 'new'",
            (user_id,),
        ).fetchone()
        return int(row["n"])

    def create_booking(self, payload: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO bookings (
                    user_id, hall, visit_date, slot_label, guests, guest_name, phone,
                    price_each, status, created_at, rank_title, request_coals, visit_coals, price_flat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?, 0, ?)
                """,
                (
                    payload["user_id"],
                    payload["hall"],
                    payload["visit_date"],
                    payload["slot_label"],
                    payload["guests"],
                    payload["guest_name"],
                    payload["phone"],
                    payload["price_each"],
                    _now(),
                    payload["rank_title"],
                    REQUEST_COALS,
                    int(payload.get("price_flat") or 0),
                ),
            )
            self._add_coals(payload["user_id"], REQUEST_COALS)
            self._grant(payload["user_id"], "table")
            self._conn.commit()
            return int(cur.lastrowid)

    def booking(self, booking_id: int) -> sqlite3.Row | None:
        return self._conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()

    def pending(self) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM bookings WHERE status = 'new' ORDER BY id DESC LIMIT 20"
        ).fetchall()

    def set_status(self, booking_id: int, status: str) -> sqlite3.Row | None:
        with self._lock:
            row = self.booking(booking_id)
            if row is None:
                return None
            if status == "confirmed" and row["status"] == "new":
                self._conn.execute(
                    "UPDATE bookings SET status = 'confirmed', visit_coals = ? WHERE id = ?",
                    (VISIT_COALS, booking_id),
                )
                self._add_coals(row["user_id"], VISIT_COALS)
                self._conn.execute(
                    "UPDATE users SET visits = visits + 1 WHERE user_id = ?",
                    (row["user_id"],),
                )
                visits = self.user(row["user_id"])["visits"]
                self._grant(row["user_id"], "first_steam")
                if visits >= 2:
                    self._grant(row["user_id"], "returned")
            elif status == "declined" and row["status"] == "new":
                self._conn.execute("UPDATE bookings SET status = 'declined' WHERE id = ?", (booking_id,))
                self._add_coals(row["user_id"], -int(row["request_coals"]))
            elif status == "cancelled" and row["status"] == "new":
                self._conn.execute("UPDATE bookings SET status = 'cancelled' WHERE id = ?", (booking_id,))
                self._add_coals(row["user_id"], -int(row["request_coals"]))
            elif status == "missed" and row["status"] == "confirmed":
                self._conn.execute("UPDATE bookings SET status = 'missed' WHERE id = ?", (booking_id,))
                self._add_coals(row["user_id"], -int(row["visit_coals"]))
                self._conn.execute(
                    "UPDATE users SET visits = MAX(visits - 1, 0) WHERE user_id = ?",
                    (row["user_id"],),
                )
            else:
                return row
            self._conn.commit()
            return self.booking(booking_id)

    def note_start(self, user_id: int) -> list[str]:
        return self._once_flag(user_id, "got_start", "entered", 8)

    def note_hall(self, user_id: int, hall: str) -> list[str]:
        column = {"male": "saw_male", "female": "saw_female"}.get(hall)
        if column is None:
            return []
        notes = self._once_flag(user_id, column, None, 4)
        user = self.user(user_id)
        if user["saw_male"] and user["saw_female"]:
            if self._grant(user_id, "both"):
                notes.append("знак «Два берега»")
                self._conn.commit()
        return notes

    def note_tariffs(self, user_id: int) -> list[str]:
        return self._once_flag(user_id, "saw_tariffs", None, 2)

    def note_schedule(self, user_id: int, day: str) -> list[str]:
        with self._lock:
            user = self.user(user_id)
            if user["schedule_day"] == day:
                return []
            self._conn.execute("UPDATE users SET schedule_day = ? WHERE user_id = ?", (day, user_id))
            self._add_coals(user_id, 2)
            self._conn.commit()
            return [coals_phrase(2)]

    def note_ritual(self, user_id: int, day: str) -> list[str]:
        with self._lock:
            user = self.user(user_id)
            if user["ritual_day"] == day:
                return []
            self._conn.execute(
                "UPDATE users SET ritual_day = ?, ritual_count = ritual_count + 1 WHERE user_id = ?",
                (day, user_id),
            )
            self._add_coals(user_id, 3)
            notes = [coals_phrase(3)]
            count = self.user(user_id)["ritual_count"]
            if count >= 3 and self._grant(user_id, "ritualist"):
                notes.append("знак «Три ритуала»")
            self._conn.commit()
            return notes

    def join_waitlist(self, user_id: int, space: str) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO waitlist (user_id, space, created_at) VALUES (?, ?, ?)",
                    (user_id, space, _now()),
                )
                self._add_coals(user_id, 4)
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def _once_flag(self, user_id: int, column: str, achievement: str | None, coals: int) -> list[str]:
        with self._lock:
            user = self.user(user_id)
            if user[column]:
                return []
            self._conn.execute(f"UPDATE users SET {column} = 1 WHERE user_id = ?", (user_id,))
            self._add_coals(user_id, coals)
            notes = [coals_phrase(coals)]
            if achievement and self._grant(user_id, achievement):
                notes.append(f"знак «{ACHIEVEMENTS[achievement]}»")
            self._conn.commit()
            return notes

    def _add_coals(self, user_id: int, delta: int) -> None:
        self._conn.execute(
            "UPDATE users SET coals = MAX(coals + ?, 0) WHERE user_id = ?",
            (delta, user_id),
        )

    def _grant(self, user_id: int, code: str) -> bool:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO achievements (user_id, code, earned_at) VALUES (?, ?, ?)",
            (user_id, code, _now()),
        )
        return cur.rowcount == 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
