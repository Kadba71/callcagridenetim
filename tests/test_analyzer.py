from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from analyzer import _analyze_person_day, analyze_excel, summarize_after_hours_excel
from storage import DepartmentRule, Storage


RULE = DepartmentRule(
    department="DİŞ EKİP",
    max_wait_minutes=15,
    morning_latest_start="11:10",
    break_pre_earliest_leave="13:50",
    break_start="14:00",
    break_end="15:00",
    break_post_latest_start="15:15",
    shift_end_earliest_leave="18:50",
)


def test_partial_cutoff_does_not_flag_future_unseen_call() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 11, 28, 0),
            "call_end": datetime(2026, 3, 8, 11, 28, 30),
        },
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 11, 33, 0),
            "call_end": datetime(2026, 3, 8, 11, 34, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 11, 30, 0))

    assert not any("İki çağrı arası bekleme süresi aşıldı" in item for item in result.violations)


def test_morning_start_allows_seconds_within_same_minute() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 11, 10, 30),
            "call_end": datetime(2026, 3, 8, 11, 12, 0),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 11, 20, 0))

    assert not any("Sabah ilk çağrı geç başladı" in item for item in result.violations)


def test_morning_start_flags_next_minute_as_violation() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 11, 11, 0),
            "call_end": datetime(2026, 3, 8, 11, 12, 0),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 11, 20, 0))

    assert any("Sabah ilk çağrı geç başladı" in item for item in result.violations)


def test_break_pre_allows_seconds_within_same_minute() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 11, 0, 0),
            "call_end": datetime(2026, 3, 8, 13, 49, 30),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 13, 55, 0))

    assert not any("Mola öncesi erken çıktı" in item for item in result.violations)


def test_break_pre_flags_full_minute_early_exit() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 11, 0, 0),
            "call_end": datetime(2026, 3, 8, 13, 49, 0),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 13, 55, 0))

    assert any("Mola öncesi erken çıktı" in item for item in result.violations)


def test_break_pre_does_not_flag_call_overlapping_break_start() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "akin",
            "call_start": datetime(2026, 3, 8, 13, 58, 0),
            "call_end": datetime(2026, 3, 8, 14, 2, 0),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 14, 10, 0))

    assert not any("Mola öncesi erken çıktı" in item for item in result.violations)


def test_break_post_allows_seconds_within_same_minute() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 13, 50, 0),
            "call_end": datetime(2026, 3, 8, 13, 55, 0),
        },
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 15, 15, 30),
            "call_end": datetime(2026, 3, 8, 15, 16, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 15, 30, 0))

    assert not any("Mola sonrası geç başladı" in item for item in result.violations)


def test_break_post_flags_next_minute_start() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 13, 50, 0),
            "call_end": datetime(2026, 3, 8, 13, 55, 0),
        },
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 15, 16, 0),
            "call_end": datetime(2026, 3, 8, 15, 17, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 15, 30, 0))

    assert any("Mola sonrası geç başladı" in item for item in result.violations)


def test_break_post_does_not_flag_call_overlapping_break_end() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 14, 55, 0),
            "call_end": datetime(2026, 3, 8, 15, 5, 0),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 15, 30, 0))

    assert not any("Mola sonrası" in item for item in result.violations)


def test_shift_end_allows_seconds_within_same_minute() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "uzay",
            "call_start": datetime(2026, 3, 8, 18, 49, 0),
            "call_end": datetime(2026, 3, 8, 18, 49, 30),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 19, 0, 0))

    assert not any("Mesai sonundan önce çıktı" in item for item in result.violations)


def test_shift_end_flags_full_minute_early_exit() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "uzay",
            "call_start": datetime(2026, 3, 8, 18, 48, 0),
            "call_end": datetime(2026, 3, 8, 18, 49, 0),
        }
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 19, 0, 0))

    assert any("Mesai sonundan önce çıktı" in item for item in result.violations)


def test_cross_break_gap_is_not_reported_as_wait_violation() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 13, 49, 30),
            "call_end": datetime(2026, 3, 8, 13, 50, 39),
        },
        {
            "department": "DİŞ EKİP",
            "person": "burak",
            "call_start": datetime(2026, 3, 8, 15, 4, 0),
            "call_end": datetime(2026, 3, 8, 15, 12, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 15, 20, 0))

    assert not any("İki çağrı arası bekleme süresi aşıldı" in item for item in result.violations)


def test_cross_break_gap_keeps_non_break_wait_time() -> None:
    rule = DepartmentRule(
        department="DİŞ EKİP",
        max_wait_minutes=5,
        morning_latest_start="12:30",
        break_pre_earliest_leave="11:55",
        break_start="12:00",
        break_end="13:00",
        break_post_latest_start="13:10",
        shift_end_earliest_leave="18:00",
    )
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "ali",
            "call_start": datetime(2026, 3, 8, 11, 58, 0),
            "call_end": datetime(2026, 3, 8, 11, 59, 0),
        },
        {
            "department": "DİŞ EKİP",
            "person": "ali",
            "call_start": datetime(2026, 3, 8, 13, 8, 0),
            "call_end": datetime(2026, 3, 8, 13, 9, 0),
        },
    ]

    result = _analyze_person_day(rows, rule, [], datetime(2026, 3, 8, 13, 9, 0))

    assert any("İki çağrı arası bekleme süresi aşıldı" in item for item in result.violations)


def test_cross_break_gap_does_not_sum_separate_short_segments() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "ali",
            "call_start": datetime(2026, 3, 8, 13, 40, 0),
            "call_end": datetime(2026, 3, 8, 13, 52, 0),
        },
        {
            "department": "DİŞ EKİP",
            "person": "ali",
            "call_start": datetime(2026, 3, 8, 15, 8, 0),
            "call_end": datetime(2026, 3, 8, 15, 12, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 15, 20, 0))

    assert not any("İki çağrı arası bekleme süresi aşıldı" in item for item in result.violations)


def test_cross_break_gap_reports_only_longest_contiguous_segment() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "ali",
            "call_start": datetime(2026, 3, 8, 13, 49, 0),
            "call_end": datetime(2026, 3, 8, 13, 50, 0),
        },
        {
            "department": "DİŞ EKİP",
            "person": "ali",
            "call_start": datetime(2026, 3, 8, 15, 16, 0),
            "call_end": datetime(2026, 3, 8, 15, 20, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 15, 30, 0))

    assert any("15:00:00 -> 15:16:00 = 16:00" in item for item in result.violations)


def test_post_shift_gap_is_not_reported_as_wait_violation() -> None:
    rows = [
        {
            "department": "DİŞ EKİP",
            "person": "uzay",
            "call_start": datetime(2026, 3, 8, 18, 49, 0),
            "call_end": datetime(2026, 3, 8, 18, 50, 15),
        },
        {
            "department": "DİŞ EKİP",
            "person": "uzay",
            "call_start": datetime(2026, 3, 8, 19, 16, 56),
            "call_end": datetime(2026, 3, 8, 19, 18, 0),
        },
    ]

    result = _analyze_person_day(rows, RULE, [], datetime(2026, 3, 8, 19, 30, 0))

    assert not any("İki çağrı arası bekleme süresi aşıldı" in item for item in result.violations)


def test_analyze_excel_finds_header_below_first_fifteen_rows(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.set_rule(
        DepartmentRule(
            department="SATIŞ",
            max_wait_minutes=15,
            morning_latest_start="09:30",
            break_pre_earliest_leave="11:55",
            break_start="12:00",
            break_end="13:00",
            break_post_latest_start="13:10",
            shift_end_earliest_leave="18:00",
        )
    )

    rows = [["meta", "meta", "meta", "meta", "meta"] for _ in range(20)]
    rows.append(["ARAMA TARİHİ", "ARAMA SAATİ", "KONUŞMA SÜRESİ", "ÇALDIRMA SÜRESİ", "DAHİLİ ADI"])
    rows.append(["08.03.2026", "09:00", "00:02:00", "00:00:10", "Ali - O"])
    frame = pd.DataFrame(rows)
    file_path = tmp_path / "late_header.xlsx"
    frame.to_excel(file_path, index=False, header=False)

    results, missing_departments, _report_path, warnings = analyze_excel(file_path, storage, "SATIŞ")

    assert results == []
    assert missing_departments == []
    assert warnings == []


def test_analyze_excel_rejects_invalid_headerless_fallback(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.set_rule(
        DepartmentRule(
            department="SATIŞ",
            max_wait_minutes=15,
            morning_latest_start="08:30",
            break_pre_earliest_leave="11:55",
            break_start="12:00",
            break_end="13:00",
            break_post_latest_start="13:10",
            shift_end_earliest_leave="18:00",
        )
    )

    frame = pd.DataFrame(
        [
            ["x", "not-a-date", "not-a-time", "x", "bad", "bad", "unknown"],
            ["y", "still-bad", "still-bad", "y", "bad", "bad", "unknown"],
        ]
    )
    file_path = tmp_path / "invalid_fallback.xlsx"
    frame.to_excel(file_path, index=False, header=False)

    with pytest.raises(ValueError, match="sabit sütun düzeni doğrulanamadı"):
        analyze_excel(file_path, storage, "SATIŞ")


def test_analyze_excel_uses_excel_numeric_talk_duration_for_wait_check(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.set_rule(
        DepartmentRule(
            department="SATIŞ",
            max_wait_minutes=10,
            morning_latest_start="13:00",
            break_pre_earliest_leave="17:00",
            break_start="17:30",
            break_end="18:00",
            break_post_latest_start="18:05",
            shift_end_earliest_leave="23:00",
        )
    )

    frame = pd.DataFrame(
        {
            "ARAMA TARİHİ": ["08.03.2026", "08.03.2026"],
            "ARAMA SAATİ": ["12:00", "12:35"],
            "KONUŞMA SÜRESİ": [30 / 1440, 1 / 1440],
            "ÇALDIRMA SÜRESİ": [0, 0],
            "DAHİLİ ADI": ["Ali - O", "Ali - O"],
        }
    )
    file_path = tmp_path / "numeric_duration.xlsx"
    frame.to_excel(file_path, index=False)

    results, missing_departments, _report_path, warnings = analyze_excel(file_path, storage, "SATIŞ")

    assert results == []
    assert missing_departments == []
    assert warnings == []


def test_analyze_excel_merges_same_person_with_spacing_variants(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.set_rule(
        DepartmentRule(
            department="SATIŞ",
            max_wait_minutes=20,
            morning_latest_start="08:30",
            break_pre_earliest_leave="11:55",
            break_start="12:00",
            break_end="13:00",
            break_post_latest_start="13:10",
            shift_end_earliest_leave="18:00",
        )
    )

    frame = pd.DataFrame(
        {
            "ARAMA TARİHİ": ["08.03.2026", "08.03.2026", "08.03.2026"],
            "ARAMA SAATİ": ["13:50", "15:13", "15:50"],
            "KONUŞMA SÜRESİ": ["00:01:00", "00:01:00", "00:01:00"],
            "ÇALDIRMA SÜRESİ": [0, 0, 0],
            "DAHİLİ ADI": ["Ahmet Yılmaz - O", "Ahmet   Yılmaz - O", "AHMET YILMAZ - O"],
        }
    )
    file_path = tmp_path / "person_variants.xlsx"
    frame.to_excel(file_path, index=False)

    results, missing_departments, _report_path, warnings = analyze_excel(file_path, storage, "SATIŞ", "16:00")

    assert missing_departments == []
    assert warnings == []
    assert len(results) == 1
    assert results[0].person == "Ahmet Yılmaz"
    assert results[0].last_call_time == "08.03.2026 15:51:00"
    assert any("15:14:00 -> 15:50:00 = 36:00" in item for item in results[0].violations)


def test_analyze_excel_sorts_mixed_call_rows_by_call_time(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.set_rule(
        DepartmentRule(
            department="SATIŞ",
            max_wait_minutes=20,
            morning_latest_start="08:30",
            break_pre_earliest_leave="13:50",
            break_start="14:00",
            break_end="15:00",
            break_post_latest_start="15:15",
            shift_end_earliest_leave="18:00",
        )
    )

    frame = pd.DataFrame(
        {
            "ARAMA TARİHİ": ["08.03.2026", "08.03.2026", "08.03.2026"],
            "ARAMA SAATİ": ["15:50", "13:50", "15:13"],
            "KONUŞMA SÜRESİ": ["00:01:00", "00:01:00", "00:01:00"],
            "ÇALDIRMA SÜRESİ": [0, 0, 0],
            "DAHİLİ ADI": ["Ahmet Yılmaz - O", "Ahmet Yılmaz - O", "Ahmet Yılmaz - O"],
        }
    )
    file_path = tmp_path / "mixed_order.xlsx"
    frame.to_excel(file_path, index=False)

    results, missing_departments, _report_path, warnings = analyze_excel(file_path, storage, "SATIŞ", "16:00")

    assert missing_departments == []
    assert warnings == []
    assert len(results) == 1
    assert results[0].person == "Ahmet Yılmaz"
    assert results[0].last_call_time == "08.03.2026 15:51:00"
    assert any("15:14:00 -> 15:50:00 = 36:00" in item for item in results[0].violations)


def test_summarize_after_hours_excel_returns_person_stats_and_non_workers(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "bot.db")
    storage.set_rule(
        DepartmentRule(
            department="SATIŞ",
            max_wait_minutes=15,
            morning_latest_start="08:30",
            break_pre_earliest_leave="11:55",
            break_start="12:00",
            break_end="13:00",
            break_post_latest_start="13:10",
            shift_end_earliest_leave="18:00",
        )
    )

    frame = pd.DataFrame(
        {
            "ARAMA TARİHİ": ["08.03.2026", "08.03.2026", "08.03.2026", "08.03.2026"],
            "ARAMA SAATİ": ["18:50", "19:05", "19:20", "18:40"],
            "KONUŞMA SÜRESİ": ["00:05:00", "00:10:00", "00:02:30", "00:03:00"],
            "ÇALDIRMA SÜRESİ": [0, 0, 0, 0],
            "DAHİLİ ADI": ["Ahmet - O", "Ahmet - O", "Ahmet - O", "Mehmet - O"],
        }
    )
    file_path = tmp_path / "after_hours.xlsx"
    frame.to_excel(file_path, index=False)

    summaries, inactive_people, warnings = summarize_after_hours_excel(file_path, storage, "SATIŞ", "19:00")

    assert warnings == []
    assert len(summaries) == 1
    assert summaries[0].person == "Ahmet"
    assert summaries[0].call_count == 2
    assert summaries[0].total_talk_duration == "12 dakika 30 saniye"
    assert inactive_people == {"08.03.2026": ["Mehmet"]}
