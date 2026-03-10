from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from analyzer import PersonAnalysis
from bot import (
    MAX_TELEGRAM_MESSAGE_LENGTH,
    _build_rule,
    _format_violation_result,
    _parse_rule_command,
    _parse_upload_command,
    _send_chunked_text,
)
from storage import Storage, normalize_department_name, normalize_person_name


class DummyMessage:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def reply_text(self, text: str) -> None:
        self.calls.append(text)


class DummyUpdate:
    def __init__(self) -> None:
        self.message = DummyMessage()


def test_parse_upload_command_supports_comma_separator() -> None:
    request = _parse_upload_command("Diş   ekip, 12:00")
    assert request.department == "DİŞ EKİP"
    assert request.control_time == "12:00"
    assert request.mode == "violations"


def test_parse_upload_command_supports_after_hours_mode() -> None:
    request = _parse_upload_command("Satış 19:00 sonra")

    assert request.department == "SATIŞ"
    assert request.control_time == "19:00"
    assert request.mode == "after-hours"


def test_parse_rule_command_validates_time_order() -> None:
    with pytest.raises(ValueError):
        _parse_rule_command("Satış, 15, 08:30, 13:30, 12:00-13:00, 13:10, 18:00")


def test_parse_rule_command_normalizes_department() -> None:
    rule = _parse_rule_command("diş ekip, 15, 08:30, 11:55, 12:00-13:00, 13:10, 18:00")
    assert rule.department == normalize_department_name("diş ekip")
    assert rule.max_wait_minutes == 15


def test_build_rule_rejects_invalid_shift_order() -> None:
    with pytest.raises(ValueError):
        _build_rule("Satış", 15, "08:30", "11:55", "12:00", "13:00", "12:50", "18:00")


def test_normalize_person_name_supports_turkish_characters() -> None:
    assert normalize_person_name("ahmet yılmaz") == "AHMET YILMAZ"


def test_storage_leave_person_roundtrip(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.add_leave_person("Ahmet   Yılmaz")

    assert "AHMET YILMAZ" in storage.get_leave_people_set()
    assert storage.list_leave_people() == ["Ahmet Yılmaz"]


def test_send_chunked_text_splits_oversized_single_block() -> None:
    update = DummyUpdate()

    asyncio.run(_send_chunked_text(update, ["x" * (MAX_TELEGRAM_MESSAGE_LENGTH + 100)]))

    assert len(update.message.calls) == 2
    assert len(update.message.calls[0]) == MAX_TELEGRAM_MESSAGE_LENGTH
    assert len(update.message.calls[1]) == 100


def test_format_violation_result_includes_last_call_time() -> None:
    result = PersonAnalysis(
        person="Ahmet Yılmaz",
        department="SATIŞ",
        report_date="10.03.2026",
        last_call_time="10.03.2026 18:42:00",
        violations=["Mesai sonundan önce çıktı (18:42:00 < 19:00)"],
        supervisor="Tanımsız",
    )

    text = _format_violation_result(result)

    assert "Personel: Ahmet Yılmaz" in text
    assert "Kural ihlalleri:" in text
    assert "Son çağrı saati: 10.03.2026 18:42:00" in text
