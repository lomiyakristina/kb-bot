"""SQLite: гости, заявки, знаки, лист ожидания."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock

from content import ACHIEVEMENTS
from logic import coals_phrase
from paths import data_dir

DB_PATH = data_dir() / "zhar.sqlite"

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
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                label TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        self._conn.commit()
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(bookings)")}
        if "price_flat" not in columns:
            self._conn.execute("ALTER TABLE bookings ADD COLUMN price_flat INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        user_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(users)")}
        if "start_count" not in user_columns:
            self._conn.execute("ALTER TABLE users ADD COLUMN start_count INTEGER NOT NULL DEFAULT 0")
            self._conn.execute("ALTER TABLE users ADD COLUMN last_start_at TEXT")
            self._conn.execute(
                "UPDATE users SET start_count = 1, last_start_at = created_at WHERE got_start = 1 AND start_count = 0"
            )
            self._conn.commit()
        user_columns = {row[1] for row in self._conn.execute("PRAGMA table_info(users)")}
        if "blocked" not in user_columns:
            self._conn.execute("ALTER TABLE users ADD COLUMN blocked INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()
        self._backfill_steps()

    def _backfill_steps(self) -> None:
        """Старые заходы были до журнала шагов — дописываем их один раз."""
        people = self._conn.execute(
            "SELECT user_id, created_at, start_count, last_start_at, saw_male, saw_female, saw_tariffs, schedule_day FROM users"
        ).fetchall()
        for person in people:
            user_id = int(person["user_id"])
            has_start = self._conn.execute(
                "SELECT 1 FROM events WHERE user_id = ? AND kind = 'start' LIMIT 1",
                (user_id,),
            ).fetchone()
            if int(person["start_count"] or 0) > 0 and not has_start:
                when = person["last_start_at"] or person["created_at"]
                self._conn.execute(
                    "INSERT INTO events (user_id, kind, label, created_at) VALUES (?, 'start', 'first', ?)",
                    (user_id, when),
                )
            flags = (
                ("saw_male", "Мужской"),
                ("saw_female", "Женский"),
                ("saw_tariffs", "Тарифы"),
            )
            for column, label in flags:
                if not int(person[column] or 0):
                    continue
                seen = self._conn.execute(
                    "SELECT 1 FROM events WHERE user_id = ? AND kind = 'button' AND label = ? LIMIT 1",
                    (user_id, label),
                ).fetchone()
                if not seen:
                    self._conn.execute(
                        "INSERT INTO events (user_id, kind, label, created_at) VALUES (?, 'button', ?, ?)",
                        (user_id, label, person["created_at"]),
                    )
            if person["schedule_day"]:
                seen = self._conn.execute(
                    "SELECT 1 FROM events WHERE user_id = ? AND kind = 'button' AND label = 'Расписание паров' LIMIT 1",
                    (user_id,),
                ).fetchone()
                if not seen:
                    self._conn.execute(
                        "INSERT INTO events (user_id, kind, label, created_at) VALUES (?, 'button', 'Расписание паров', ?)",
                        (user_id, person["created_at"]),
                    )
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

    def user_bookings(self, user_id: int, limit: int = 5) -> list[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM bookings WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()

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
            self._log_unlocked(payload["user_id"], "booking", "new")
            self._conn.commit()
            self._save_ledger()
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
            self._log_unlocked(row["user_id"], "booking", status)
            self._conn.commit()
            self._save_ledger()
            return self.booking(booking_id)

    def note_start(self, user_id: int) -> list[str]:
        return self._once_flag(user_id, "got_start", "entered", 8)

    def mark_start(self, user_id: int) -> tuple[bool, sqlite3.Row]:
        with self._lock:
            user = self.user(user_id)
            first = int(user["start_count"] or 0) == 0
            self._conn.execute(
                "UPDATE users SET last_start_at = ?, start_count = start_count + 1 WHERE user_id = ?",
                (_now(), user_id),
            )
            self._log_unlocked(user_id, "start", "first" if first else "again")
            self._conn.commit()
            self._save_ledger()
            return first, self.user(user_id)

    def starts(self, limit: int = 30) -> tuple[int, list[sqlite3.Row]]:
        total = self._conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE start_count > 0"
        ).fetchone()
        rows = self._conn.execute(
            "SELECT * FROM users WHERE start_count > 0 ORDER BY last_start_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return int(total["n"]), rows

    def log(self, user_id: int, kind: str, label: str = "") -> None:
        with self._lock:
            self._log_unlocked(user_id, kind, label)
            self._conn.commit()
            self._save_ledger()

    def refresh_ledger(self) -> Path | None:
        with self._lock:
            return self._save_ledger()

    def _save_ledger(self) -> Path | None:
        try:
            from ledger import write
            return write(self._conn)
        except Exception:
            return None

    def _log_unlocked(self, user_id: int, kind: str, label: str = "") -> None:
        self._conn.execute(
            "INSERT INTO events (user_id, kind, label, created_at) VALUES (?, ?, ?, ?)",
            (user_id, kind, label, _now()),
        )

    def set_blocked(self, user_id: int, blocked: bool = True) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE users SET blocked = ? WHERE user_id = ?",
                (1 if blocked else 0, user_id),
            )
            self._conn.commit()
            self._save_ledger()

    def audience(self) -> list[int]:
        rows = self._conn.execute(
            "SELECT user_id FROM users WHERE start_count > 0 AND blocked = 0"
        ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def stats(self) -> dict:
        day = _now()[:10]

        def count(sql: str, args: tuple = ()) -> int:
            return int(self._conn.execute(sql, args).fetchone()["n"])

        buttons = self._conn.execute(
            """
            SELECT label, COUNT(*) AS n FROM events
            WHERE kind = 'button' GROUP BY label ORDER BY n DESC LIMIT 8
            """
        ).fetchall()
        bookings = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM bookings GROUP BY status"
        ).fetchall()
        return {
            "people": count("SELECT COUNT(*) AS n FROM users WHERE start_count > 0"),
            "today": count(
                "SELECT COUNT(*) AS n FROM users WHERE start_count > 0 AND last_start_at LIKE ?",
                (day + "%",),
            ),
            "first_today": count(
                "SELECT COUNT(*) AS n FROM events WHERE kind = 'start' AND label = 'first' AND created_at LIKE ?",
                (day + "%",),
            ),
            "starts": count("SELECT COUNT(*) AS n FROM events WHERE kind = 'start'"),
            "blocked": count("SELECT COUNT(*) AS n FROM users WHERE blocked = 1"),
            "buttons": [(row["label"], int(row["n"])) for row in buttons],
            "bookings": {row["status"]: int(row["n"]) for row in bookings},
        }

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
