from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from storage import DepartmentRule, Storage, normalize_person_name


NAME_SUFFIX_PATTERN = re.compile(r"^\s*(.*?)\s*-\s*([0OoKk])\s*$")


@dataclass(slots=True)
class PersonAnalysis:
    person: str
    department: str
    report_date: str
    last_call_time: str
    violations: list[str]
    supervisor: str


@dataclass(slots=True)
class AfterHoursSummary:
    person: str
    department: str
    report_date: str
    call_count: int
    total_talk_duration: str


HEADER_ALIASES = {
    "aramasaati": "call_time",
    "aramatarihi": "call_date",
    "dahiliadi": "agent_name",
    "departmanadi": "department",
    "konusmasuresi": "talk_duration",
    "caldirmasuresi": "ring_duration",
}

REQUIRED_COLUMNS = {"call_time", "call_date", "agent_name", "talk_duration", "ring_duration"}


def _iter_non_empty_rows(dataframe: pd.DataFrame, limit: int = 10):
    checked = 0
    for _, row in dataframe.iterrows():
        if row.isna().all():
            continue
        yield row
        checked += 1
        if checked >= limit:
            break


def _normalize_header(value: Any) -> str:
    text = str(value).strip().lower().replace("i̇", "i")
    replacements = str.maketrans({
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "İ": "i",
        "̇": "",
        "ö": "o",
        "ş": "s",
        "ü": "u",
        " ": "",
        "_": "",
        "-": "",
        ".": "",
        "/": "",
    })
    return text.translate(replacements)


def _parse_clock(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def _combine_datetime(date_value: Any, time_value: Any) -> datetime:
    date_part = pd.to_datetime(date_value, dayfirst=True, errors="coerce")
    if pd.isna(date_part):
        raise ValueError(f"Geçersiz tarih değeri: {date_value}")

    if isinstance(time_value, datetime):
        clock = time_value.time()
    else:
        clock = pd.to_datetime(str(time_value), format="%H:%M:%S", errors="coerce")
        if pd.isna(clock):
            clock = pd.to_datetime(str(time_value), format="%H:%M", errors="coerce")
        if pd.isna(clock):
            raise ValueError(f"Geçersiz saat değeri: {time_value}")
        clock = clock.to_pydatetime().time()

    return datetime.combine(date_part.date(), clock)


def _parse_duration_value(value: Any) -> pd.Timedelta:
    if pd.isna(value):
        return pd.Timedelta(seconds=0)

    if isinstance(value, pd.Timedelta):
        return value

    if isinstance(value, timedelta):
        return pd.Timedelta(value)

    if isinstance(value, datetime):
        return pd.Timedelta(
            hours=value.hour,
            minutes=value.minute,
            seconds=value.second,
            microseconds=value.microsecond,
        )

    if isinstance(value, time):
        return pd.Timedelta(
            hours=value.hour,
            minutes=value.minute,
            seconds=value.second,
            microseconds=value.microsecond,
        )

    if isinstance(value, (int, float)):
        numeric_value = float(value)
        if 0 <= numeric_value < 1:
            return pd.Timedelta(seconds=round(numeric_value * 24 * 60 * 60))
        return pd.to_timedelta(numeric_value, unit="s")

    text = str(value).strip()
    if not text:
        return pd.Timedelta(seconds=0)

    if re.fullmatch(r"\d+(?:[.,]\d+)?", text):
        numeric_value = float(text.replace(",", "."))
        if 0 <= numeric_value < 1:
            return pd.Timedelta(seconds=round(numeric_value * 24 * 60 * 60))
        return pd.to_timedelta(numeric_value, unit="s")

    parsed = pd.to_timedelta(text, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"Geçersiz süre değeri: {value}")
    return parsed


def _extract_person_name(raw_value: Any) -> str | None:
    if pd.isna(raw_value):
        return None
    match = NAME_SUFFIX_PATTERN.match(str(raw_value))
    if not match:
        return None
    person_name = " ".join(match.group(1).split())
    suffix = match.group(2).upper().replace("0", "O")
    if suffix != "O" or not person_name:
        return None
    return person_name


def _find_columns(dataframe: pd.DataFrame) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for column in dataframe.columns:
        normalized = _normalize_header(column)
        if normalized in HEADER_ALIASES:
            mapped[HEADER_ALIASES[normalized]] = column

    if not REQUIRED_COLUMNS.issubset(mapped):
        columns = list(dataframe.columns)
        if len(columns) >= 7:
            mapped.setdefault("call_date", columns[1])
            mapped.setdefault("call_time", columns[2])
            mapped.setdefault("talk_duration", columns[4])
            mapped.setdefault("ring_duration", columns[5])
            mapped.setdefault("agent_name", columns[6])
            if len(columns) >= 8:
                mapped.setdefault("department", columns[7])

    missing = REQUIRED_COLUMNS - set(mapped)
    if missing:
        raise ValueError(
            "Eksik kolonlar: "
            f"{', '.join(sorted(missing))}. Beklenen alanlar: ARAMA TARİHİ, ARAMA SAATİ, KONUŞMA SÜRESİ, ÇALDIRMA SÜRESİ, DAHİLİ ADI"
        )
    return mapped


def _validate_fallback_layout(dataframe: pd.DataFrame, column_map: dict[str, str]) -> None:
    if len(dataframe.columns) not in {7, 8}:
        raise ValueError(
            "Excel başlıkları otomatik bulunamadı ve sabit sütun düzeni doğrulanamadı. "
            "Başlıksız kullanımda 7 veya 8 sütunlu standart rapor beklenir."
        )

    valid_rows = 0
    inspected_rows = 0
    for row in _iter_non_empty_rows(dataframe):
        inspected_rows += 1
        try:
            _combine_datetime(row[column_map["call_date"]], row[column_map["call_time"]])
        except ValueError:
            continue

        if _extract_person_name(row[column_map["agent_name"]]) is None:
            continue

        valid_rows += 1

    if inspected_rows == 0 or valid_rows == 0:
        raise ValueError(
            "Excel başlıkları otomatik bulunamadı ve sabit sütun düzeni doğrulanamadı. "
            "Lütfen başlıklı standart rapor yükleyin."
        )


def _prepare_dataframe_with_header(raw_dataframe: pd.DataFrame) -> pd.DataFrame:
    best_row_index: int | None = None
    best_score = -1

    max_score = len(set(HEADER_ALIASES.values()))
    scan_limit = len(raw_dataframe)
    for row_index in range(scan_limit):
        row_values = raw_dataframe.iloc[row_index].tolist()
        score = 0
        seen_aliases: set[str] = set()
        for value in row_values:
            normalized = _normalize_header(value)
            alias = HEADER_ALIASES.get(normalized)
            if alias and alias not in seen_aliases:
                seen_aliases.add(alias)
                score += 1
        if score > best_score:
            best_score = score
            best_row_index = row_index
        if score >= max_score:
            break

    if best_row_index is None or best_score <= 0:
        raise ValueError("Excel başlık satırı bulunamadı.")

    header_row = raw_dataframe.iloc[best_row_index].fillna("")
    prepared = raw_dataframe.iloc[best_row_index + 1 :].copy()
    prepared.columns = [str(value).strip() if str(value).strip() else f"Unnamed_{index}" for index, value in enumerate(header_row)]
    prepared = prepared.dropna(how="all").reset_index(drop=True)
    return prepared


def _load_excel(file_path: Path) -> tuple[pd.DataFrame, list[str]]:
    raw_dataframe = pd.read_excel(file_path, engine="calamine", header=None)
    try:
        prepared = _prepare_dataframe_with_header(raw_dataframe)
        _find_columns(prepared)
        return prepared, []
    except ValueError:
        fallback = raw_dataframe.copy()
        fallback.columns = [f"column_{index}" for index in range(len(fallback.columns))]
        column_map = _find_columns(fallback)
        _validate_fallback_layout(fallback, column_map)
        return fallback, ["Excel başlıkları otomatik bulunamadı. Sabit sütun düzeni (B tarih, C saat, E konuşma, F çaldırma, G personel) ile analiz yapıldı."]


def _overlap_seconds(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> float:
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    delta = (earliest_end - latest_start).total_seconds()
    return max(0.0, delta)


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Yok"
    return value.strftime("%d.%m.%Y %H:%M:%S")


def _build_daily_window(base_date: datetime, start_text: str, end_text: str) -> tuple[datetime, datetime]:
    start_clock = _parse_clock(start_text)
    end_clock = _parse_clock(end_text)
    return datetime.combine(base_date.date(), start_clock), datetime.combine(base_date.date(), end_clock)


def _max_contiguous_gap_segment(
    start_dt: datetime,
    end_dt: datetime,
    break_start_dt: datetime,
    break_end_dt: datetime,
) -> tuple[float, datetime, datetime]:
    if end_dt <= start_dt:
        return 0.0, start_dt, start_dt

    segments: list[tuple[datetime, datetime]] = []
    if start_dt < break_start_dt:
        before_break_end = min(end_dt, break_start_dt)
        if before_break_end > start_dt:
            segments.append((start_dt, before_break_end))
    if end_dt > break_end_dt:
        after_break_start = max(start_dt, break_end_dt)
        if end_dt > after_break_start:
            segments.append((after_break_start, end_dt))
    if not segments:
        return 0.0, start_dt, start_dt

    best_start, best_end = max(segments, key=lambda segment: (segment[1] - segment[0]).total_seconds())
    return max(0.0, (best_end - best_start).total_seconds()), best_start, best_end


def _format_gap(seconds: float) -> str:
    total_seconds = int(seconds)
    return f"{total_seconds // 60:02d}:{total_seconds % 60:02d}"


def _format_duration_words(total_seconds: int) -> str:
    total_seconds = max(0, int(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    parts: list[str] = []
    if hours:
        parts.append(f"{hours} saat")
    if minutes or hours:
        parts.append(f"{minutes} dakika")
    parts.append(f"{seconds} saniye")
    return " ".join(parts)


def _truncate_to_minute(value: datetime) -> datetime:
    return value.replace(second=0, microsecond=0)


def _difference_seconds(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds()


def _is_late_with_minute_grace(actual: datetime, threshold: datetime) -> bool:
    return actual > threshold and _difference_seconds(actual, threshold) >= 60


def _is_early_with_minute_grace(actual: datetime, threshold: datetime) -> bool:
    return actual < threshold and _difference_seconds(threshold, actual) >= 60


def _threshold_fully_passed(reference: datetime, threshold: datetime) -> bool:
    return reference >= threshold and _difference_seconds(reference, threshold) >= 60


def _prepare_workframe(
    file_path: str | Path,
    storage: Storage,
    department_name: str | None = None,
) -> tuple[Path, pd.DataFrame, list[str]]:
    source = Path(file_path)
    dataframe, warnings = _load_excel(source)
    column_map = _find_columns(dataframe)
    selected_department = department_name.strip() if department_name else None

    workframe = dataframe.copy()
    workframe["_person_display"] = workframe[column_map["agent_name"]].apply(_extract_person_name)
    workframe = workframe[workframe["_person_display"].notna()].copy()
    workframe["_person_key"] = workframe["_person_display"].apply(normalize_person_name)
    leave_people = storage.get_leave_people_set()
    if leave_people:
        workframe = workframe[~workframe["_person_key"].isin(leave_people)].copy()

    if workframe.empty:
        raise ValueError("Excel içinde işlenecek 'isim-O' kaydı bulunamadı.")

    workframe["_call_start"] = workframe.apply(
        lambda row: _combine_datetime(row[column_map["call_date"]], row[column_map["call_time"]]),
        axis=1,
    )
    workframe["_talk_duration"] = workframe[column_map["talk_duration"]].apply(_parse_duration_value)
    workframe["_ring_duration"] = workframe[column_map["ring_duration"]].apply(_parse_duration_value)
    workframe["_call_end"] = workframe["_call_start"] + workframe["_talk_duration"] + workframe["_ring_duration"]
    if selected_department:
        workframe["_department"] = selected_department
    elif "department" in column_map:
        workframe["_department"] = workframe[column_map["department"]].fillna("Tanımsız").astype(str).str.strip()
    else:
        raise ValueError("Departman bilgisi bulunamadı. /yukle <departman> kullanın.")

    workframe = workframe.sort_values(
        ["_department", "_person_key", "_call_start", "_call_end"],
        kind="stable",
    ).reset_index(drop=True)

    return source, workframe, warnings


def _analyze_person_day(
    rows: list[dict[str, Any]],
    rule: DepartmentRule,
    supervisors: list[str],
    analysis_cutoff: datetime,
) -> PersonAnalysis:
    rows = sorted(rows, key=lambda item: item["call_start"])
    base_date = rows[0]["call_start"]
    break_start_dt, break_end_dt = _build_daily_window(base_date, rule.break_start, rule.break_end)
    morning_latest_dt = datetime.combine(base_date.date(), _parse_clock(rule.morning_latest_start))
    break_pre_earliest_leave_dt = datetime.combine(base_date.date(), _parse_clock(rule.break_pre_earliest_leave))
    break_post_latest_dt = datetime.combine(base_date.date(), _parse_clock(rule.break_post_latest_start))
    shift_end_earliest_leave_dt = datetime.combine(base_date.date(), _parse_clock(rule.shift_end_earliest_leave))

    active_rows = []
    for row in rows:
        if row["call_start"] > analysis_cutoff:
            continue
        active_rows.append(
            {
                **row,
                "call_end": min(row["call_end"], analysis_cutoff),
            }
        )

    active_rows.sort(key=lambda item: item["call_start"])

    if not active_rows:
        return PersonAnalysis(
            person=rows[0]["person"],
            department=rows[0]["department"],
            report_date=base_date.strftime("%d.%m.%Y"),
            last_call_time="Yok",
            violations=[],
            supervisor=", ".join(supervisors) if supervisors else "Tanımsız",
        )

    violations: list[str] = []
    first_call = active_rows[0]["call_start"]
    last_call_end = max(row["call_end"] for row in active_rows)
    allowed_gap_seconds = rule.max_wait_minutes * 60
    morning_control_start_dt = morning_latest_dt - timedelta(seconds=allowed_gap_seconds)
    morning_tracking_rows = [row for row in active_rows if row["call_end"] > morning_control_start_dt]

    if _threshold_fully_passed(analysis_cutoff, morning_latest_dt):
        if not morning_tracking_rows:
            violations.append(
                f"Sabah ilk çağrı geç başladı ({rule.morning_latest_start} sonrasına kaldı)"
            )
        else:
            first_morning_activity = min(
                max(row["call_start"], morning_control_start_dt)
                for row in morning_tracking_rows
            )
            if _is_late_with_minute_grace(first_morning_activity, morning_latest_dt):
                violations.append(
                    f"Sabah ilk çağrı geç başladı ({first_morning_activity.strftime('%H:%M:%S')} > {rule.morning_latest_start})"
                )

    pre_break_window_end = min(analysis_cutoff, break_start_dt)
    if _threshold_fully_passed(pre_break_window_end, break_pre_earliest_leave_dt):
        pre_break_activity_ends = [
            min(row["call_end"], pre_break_window_end)
            for row in active_rows
            if row["call_start"] < pre_break_window_end
        ]
        if pre_break_activity_ends:
            last_pre_break_end = max(pre_break_activity_ends)
            if _is_early_with_minute_grace(last_pre_break_end, break_pre_earliest_leave_dt):
                violations.append(
                    f"Mola öncesi erken çıktı ({last_pre_break_end.strftime('%H:%M:%S')} < {rule.break_pre_earliest_leave})"
                )

    if _threshold_fully_passed(analysis_cutoff, break_post_latest_dt):
        post_break_starts = [
            max(row["call_start"], break_end_dt)
            for row in active_rows
            if row["call_end"] > break_end_dt
        ]
        if not post_break_starts:
            violations.append(f"Mola sonrası çağrı geç başladı ({rule.break_post_latest_start} sonrasına kaldı)")
        else:
            first_post_break = min(post_break_starts)
            if _is_late_with_minute_grace(first_post_break, break_post_latest_dt):
                violations.append(
                    f"Mola sonrası geç başladı ({first_post_break.strftime('%H:%M:%S')} > {rule.break_post_latest_start})"
                )

    if _threshold_fully_passed(analysis_cutoff, shift_end_earliest_leave_dt) and _is_early_with_minute_grace(last_call_end, shift_end_earliest_leave_dt):
        violations.append(
            f"Mesai sonundan önce çıktı ({last_call_end.strftime('%H:%M:%S')} < {rule.shift_end_earliest_leave})"
        )

    gap_check_limit = min(analysis_cutoff, shift_end_earliest_leave_dt)
    for previous_row, current_row in zip(active_rows, active_rows[1:]):
        if previous_row["call_end"] >= gap_check_limit:
            continue

        gap_control_start = max(previous_row["call_end"], morning_control_start_dt)
        gap_control_end = min(current_row["call_start"], gap_check_limit)
        raw_gap = (gap_control_end - gap_control_start).total_seconds()
        if raw_gap <= 0:
            continue

        effective_gap, gap_start, gap_end = _max_contiguous_gap_segment(
            gap_control_start,
            gap_control_end,
            break_start_dt,
            break_end_dt,
        )
        if effective_gap > allowed_gap_seconds:
            violations.append(
                "İki çağrı arası bekleme süresi aşıldı "
                f"({gap_start.strftime('%H:%M:%S')} -> {gap_end.strftime('%H:%M:%S')} = "
                f"{_format_gap(effective_gap)})"
            )

    trailing_start = max(last_call_end, morning_control_start_dt)
    trailing_end = gap_check_limit
    if trailing_end > trailing_start:
        trailing_gap, gap_start, gap_end = _max_contiguous_gap_segment(
            trailing_start,
            trailing_end,
            break_start_dt,
            break_end_dt,
        )
        if trailing_gap > allowed_gap_seconds:
            violations.append(
                "İki çağrı arası bekleme süresi aşıldı "
                f"({gap_start.strftime('%H:%M:%S')} -> {gap_end.strftime('%H:%M:%S')} = "
                f"{_format_gap(trailing_gap)})"
            )

    return PersonAnalysis(
        person=rows[0]["person"],
        department=rows[0]["department"],
        report_date=base_date.strftime("%d.%m.%Y"),
        last_call_time=_format_datetime(last_call_end),
        violations=violations,
        supervisor=", ".join(supervisors) if supervisors else "Tanımsız",
    )


def analyze_excel(
    file_path: str | Path,
    storage: Storage,
    department_name: str | None = None,
    control_time_text: str | None = None,
) -> tuple[list[PersonAnalysis], list[str], Path, list[str]]:
    source, workframe, warnings = _prepare_workframe(file_path, storage, department_name)

    explicit_cutoff_time = _parse_clock(control_time_text) if control_time_text else None
    cutoff_map: dict[str, datetime] = {}
    for report_date, day_rows in workframe.groupby(workframe["_call_start"].dt.strftime("%Y-%m-%d")):
        day_start = day_rows["_call_start"].iloc[0].to_pydatetime() if hasattr(day_rows["_call_start"].iloc[0], "to_pydatetime") else day_rows["_call_start"].iloc[0]
        if explicit_cutoff_time is not None:
            cutoff_map[report_date] = datetime.combine(day_start.date(), explicit_cutoff_time)
        else:
            day_last_end = day_rows["_call_end"].max()
            cutoff_map[report_date] = day_last_end.to_pydatetime() if hasattr(day_last_end, "to_pydatetime") else day_last_end

    rules_map = storage.get_rules_map()
    supervisors_map = storage.supervisors_map()
    missing_departments: set[str] = set()
    results: list[PersonAnalysis] = []

    grouped_rows: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in workframe.to_dict("records"):
        department = row["_department"]
        person_key = row["_person_key"]
        call_start = row["_call_start"]
        call_end = row["_call_end"]
        report_date = call_start.strftime("%Y-%m-%d")
        key = (department, person_key, report_date)
        grouped_rows.setdefault(key, []).append(
            {
                "department": department,
                "person": row["_person_display"],
                "call_start": call_start.to_pydatetime() if hasattr(call_start, "to_pydatetime") else call_start,
                "call_end": call_end.to_pydatetime() if hasattr(call_end, "to_pydatetime") else call_end,
            }
        )

    for (department, _person, _report_date), rows in sorted(grouped_rows.items()):
        rule = rules_map.get(department)
        if rule is None:
            missing_departments.add(department)
            continue
        results.append(_analyze_person_day(rows, rule, supervisors_map.get(department, []), cutoff_map[_report_date]))

    results = [result for result in results if result.violations]

    report_rows = []
    for result in results:
        row = asdict(result)
        row["violations"] = "; ".join(result.violations)
        report_rows.append(row)

    report_frame = pd.DataFrame(report_rows)
    if report_frame.empty:
        report_frame = pd.DataFrame(columns=["person", "department", "report_date", "last_call_time", "violations", "supervisor"])

    export_path = source.with_name(f"analiz_{source.stem}.xlsx")
    report_frame.rename(
        columns={
            "person": "Personel",
            "department": "Departman",
            "report_date": "Rapor Tarihi",
            "last_call_time": "Son Çağrı Saati",
            "violations": "Kural İhlali",
            "supervisor": "Sorumlu",
        }
    ).to_excel(export_path, index=False)

    return results, sorted(missing_departments), export_path, warnings


def summarize_after_hours_excel(
    file_path: str | Path,
    storage: Storage,
    department_name: str,
    after_time_text: str,
) -> tuple[list[AfterHoursSummary], dict[str, list[str]], list[str]]:
    _source, workframe, warnings = _prepare_workframe(file_path, storage, department_name)
    after_clock = _parse_clock(after_time_text)

    workframe = workframe.copy()
    workframe["_report_date_key"] = workframe["_call_start"].dt.strftime("%Y-%m-%d")
    workframe["_report_date"] = workframe["_call_start"].dt.strftime("%d.%m.%Y")
    workframe["_after_cutoff"] = workframe["_call_start"].apply(lambda value: datetime.combine(value.date(), after_clock))

    after_frame = workframe[workframe["_call_start"] >= workframe["_after_cutoff"]].copy()

    summaries: list[AfterHoursSummary] = []
    if not after_frame.empty:
        grouped_after = after_frame.groupby(["_report_date_key", "_report_date", "_department", "_person_key"], sort=True)
        for (_date_key, report_date, department, _person_key), rows in grouped_after:
            person = rows["_person_display"].iloc[0]
            total_talk_seconds = int(rows["_talk_duration"].dt.total_seconds().sum())
            summaries.append(
                AfterHoursSummary(
                    person=person,
                    department=department,
                    report_date=report_date,
                    call_count=int(len(rows)),
                    total_talk_duration=_format_duration_words(total_talk_seconds),
                )
            )

    all_people_by_date: dict[str, dict[str, str]] = {}
    for report_date, rows in workframe.groupby("_report_date", sort=True):
        people = {
            person_key: person_display
            for person_key, person_display in rows[["_person_key", "_person_display"]].drop_duplicates().itertuples(index=False)
        }
        all_people_by_date[report_date] = people

    after_people_by_date = {
        report_date: set(rows["_person_key"].tolist())
        for report_date, rows in after_frame.groupby("_report_date", sort=True)
    }

    inactive_people = {
        report_date: sorted(
            person_display
            for person_key, person_display in people.items()
            if person_key not in after_people_by_date.get(report_date, set())
        )
        for report_date, people in all_people_by_date.items()
    }

    return summaries, inactive_people, warnings
