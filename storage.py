from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


def normalize_department_name(value: str) -> str:
    translation = str.maketrans({
        "i": "İ",
        "ı": "I",
    })
    normalized = value.strip().translate(translation).upper()
    return " ".join(normalized.split())


def normalize_person_name(value: str) -> str:
    translation = str.maketrans({
        "i": "İ",
        "ı": "I",
    })
    normalized = value.strip().translate(translation).upper()
    return " ".join(normalized.split())


@dataclass(slots=True)
class DepartmentRule:
    department: str
    max_wait_minutes: int
    morning_latest_start: str
    break_pre_earliest_leave: str
    break_start: str
    break_end: str
    break_post_latest_start: str
    shift_end_earliest_leave: str


class Storage:
    def __init__(self, db_path: str | Path = "data/bot.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS departments (
                    name TEXT PRIMARY KEY
                );

                CREATE TABLE IF NOT EXISTS supervisors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    department_name TEXT NOT NULL,
                    supervisor_name TEXT NOT NULL,
                    UNIQUE(department_name, supervisor_name),
                    FOREIGN KEY(department_name) REFERENCES departments(name) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS rules (
                    department_name TEXT PRIMARY KEY,
                    max_wait_minutes INTEGER NOT NULL,
                    morning_latest_start TEXT NOT NULL,
                    break_pre_earliest_leave TEXT NOT NULL,
                    break_start TEXT NOT NULL,
                    break_end TEXT NOT NULL,
                    break_post_latest_start TEXT NOT NULL,
                    shift_end_earliest_leave TEXT NOT NULL,
                    FOREIGN KEY(department_name) REFERENCES departments(name) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS leave_personnel (
                    normalized_name TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL
                );
                """
            )
        self._normalize_existing_departments()

    def _normalize_existing_departments(self) -> None:
        with self._connect() as connection:
            rows = connection.execute("SELECT name FROM departments").fetchall()
            for row in rows:
                original_name = row["name"]
                normalized_name = normalize_department_name(original_name)
                if normalized_name == original_name:
                    continue

                connection.execute("INSERT OR IGNORE INTO departments(name) VALUES (?)", (normalized_name,))
                connection.execute(
                    "UPDATE OR IGNORE supervisors SET department_name = ? WHERE department_name = ?",
                    (normalized_name, original_name),
                )
                connection.execute(
                    "UPDATE OR IGNORE rules SET department_name = ? WHERE department_name = ?",
                    (normalized_name, original_name),
                )
                connection.execute("DELETE FROM departments WHERE name = ?", (original_name,))

    def add_department(self, department: str) -> None:
        department = normalize_department_name(department)
        with self._connect() as connection:
            connection.execute("INSERT OR IGNORE INTO departments(name) VALUES (?)", (department,))

    def delete_department(self, department: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM departments WHERE name = ?", (normalize_department_name(department),))
            return cursor.rowcount

    def list_departments(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT name FROM departments ORDER BY name").fetchall()
        return [row["name"] for row in rows]

    def add_supervisor(self, department: str, supervisor: str) -> None:
        department = normalize_department_name(department)
        supervisor = supervisor.strip()
        self.add_department(department)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO supervisors(department_name, supervisor_name) VALUES (?, ?)",
                (department, supervisor),
            )

    def delete_supervisor(self, department: str, supervisor: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM supervisors WHERE department_name = ? AND supervisor_name = ?",
                (normalize_department_name(department), supervisor.strip()),
            )
            return cursor.rowcount

    def get_supervisors(self, department: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT supervisor_name FROM supervisors WHERE department_name = ? ORDER BY supervisor_name",
                (normalize_department_name(department),),
            ).fetchall()
        return [row["supervisor_name"] for row in rows]

    def set_rule(self, rule: DepartmentRule) -> None:
        department = normalize_department_name(rule.department)
        self.add_department(department)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rules(
                    department_name,
                    max_wait_minutes,
                    morning_latest_start,
                    break_pre_earliest_leave,
                    break_start,
                    break_end,
                    break_post_latest_start,
                    shift_end_earliest_leave
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(department_name) DO UPDATE SET
                    max_wait_minutes = excluded.max_wait_minutes,
                    morning_latest_start = excluded.morning_latest_start,
                    break_pre_earliest_leave = excluded.break_pre_earliest_leave,
                    break_start = excluded.break_start,
                    break_end = excluded.break_end,
                    break_post_latest_start = excluded.break_post_latest_start,
                    shift_end_earliest_leave = excluded.shift_end_earliest_leave
                """,
                (
                    department,
                    rule.max_wait_minutes,
                    rule.morning_latest_start,
                    rule.break_pre_earliest_leave,
                    rule.break_start,
                    rule.break_end,
                    rule.break_post_latest_start,
                    rule.shift_end_earliest_leave,
                ),
            )

    def get_rule(self, department: str) -> DepartmentRule | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM rules WHERE department_name = ?",
                (normalize_department_name(department),),
            ).fetchone()
        if row is None:
            return None
        return DepartmentRule(
            department=row["department_name"],
            max_wait_minutes=row["max_wait_minutes"],
            morning_latest_start=row["morning_latest_start"],
            break_pre_earliest_leave=row["break_pre_earliest_leave"],
            break_start=row["break_start"],
            break_end=row["break_end"],
            break_post_latest_start=row["break_post_latest_start"],
            shift_end_earliest_leave=row["shift_end_earliest_leave"],
        )

    def get_rules_map(self) -> dict[str, DepartmentRule]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM rules").fetchall()
        return {
            row["department_name"]: DepartmentRule(
                department=row["department_name"],
                max_wait_minutes=row["max_wait_minutes"],
                morning_latest_start=row["morning_latest_start"],
                break_pre_earliest_leave=row["break_pre_earliest_leave"],
                break_start=row["break_start"],
                break_end=row["break_end"],
                break_post_latest_start=row["break_post_latest_start"],
                shift_end_earliest_leave=row["shift_end_earliest_leave"],
            )
            for row in rows
        }

    def delete_rule(self, department: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM rules WHERE department_name = ?",
                (normalize_department_name(department),),
            )
            return cursor.rowcount

    def update_max_wait_minutes(self, department: str, minutes: int) -> bool:
        department_name = normalize_department_name(department)
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE rules SET max_wait_minutes = ? WHERE department_name = ?",
                (minutes, department_name),
            )
            return cursor.rowcount > 0

    def supervisors_map(self) -> dict[str, list[str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT department_name, supervisor_name FROM supervisors ORDER BY department_name, supervisor_name"
            ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["department_name"], []).append(row["supervisor_name"])
        return result

    def get_status_summary(self) -> dict[str, int]:
        with self._connect() as connection:
            department_count = connection.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
            rule_count = connection.execute("SELECT COUNT(*) FROM rules").fetchone()[0]
            supervisor_count = connection.execute("SELECT COUNT(*) FROM supervisors").fetchone()[0]
            leave_count = connection.execute("SELECT COUNT(*) FROM leave_personnel").fetchone()[0]
        return {
            "departments": int(department_count),
            "rules": int(rule_count),
            "supervisors": int(supervisor_count),
            "leave_personnel": int(leave_count),
        }

    def add_leave_person(self, person_name: str) -> None:
        normalized_name = normalize_person_name(person_name)
        display_name = " ".join(person_name.strip().split())
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO leave_personnel(normalized_name, display_name) VALUES (?, ?) ON CONFLICT(normalized_name) DO UPDATE SET display_name = excluded.display_name",
                (normalized_name, display_name),
            )

    def delete_leave_person(self, person_name: str) -> int:
        normalized_name = normalize_person_name(person_name)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM leave_personnel WHERE normalized_name = ?",
                (normalized_name,),
            )
            return cursor.rowcount

    def list_leave_people(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT display_name FROM leave_personnel ORDER BY display_name"
            ).fetchall()
        return [row["display_name"] for row in rows]

    def get_leave_people_set(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT normalized_name FROM leave_personnel"
            ).fetchall()
        return {row["normalized_name"] for row in rows}
