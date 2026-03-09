from __future__ import annotations

from dataclasses import dataclass, replace
import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from analyzer import analyze_excel, summarize_after_hours_excel
from storage import DepartmentRule, Storage, normalize_department_name, normalize_person_name


logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.ExtBot").setLevel(logging.WARNING)

load_dotenv()

HELP_TEXT = """
Yardım:
/help

İhlal kontrolü:
/yukle <departman>
/yukle <departman>, <HH:MM>

Mesai sonrası özeti:
/yukle <departman> <HH:MM> sonra

Örnek yükleme komutları:
/yukle Satış
/yukle Satış, 12:00
/yukle Satış 19:00 sonra

Kural ve tanım komutları:
/departmanekle <departman>
/departmansil <departman>
/departmanliste
/izin <personel>
/izinsil <personel>
/izinliste
/sorumluekle <departman>, <sorumlu>
/sorumlusil <departman>, <sorumlu>
/sorumluliste <departman>
/kuralekle <departman>, <max_bekleme_dk>, <sabah_en_gec>, <mola_oncesi_en_erken>, <mola_baslangic-mola_bitis>, <mola_sonrasi_en_gec>, <mesai_sonu_en_erken>
/sabahengec <HH:MM>, <departman>
/molaoncesi <HH:MM>, <departman>
/molaaraligi <HH:MM-HH:MM>, <departman>
/molasonrasi <HH:MM>, <departman>
/mesaisonu <HH:MM>, <departman>
/kuralgoster <departman>
/kuralliste
/kuralsil <departman>
/cagriaraligi <sure_dk>, <departman>
/durum

Örnek tanım komutları:
/departmanekle Satış
/izin Ahmet Yılmaz
/sorumluekle Satış, Ayşe Kaya
/kuralekle Satış, 15, 08:30, 11:55, 12:00-13:00, 13:10, 18:00
/sabahengec 08:45, Satış
/molaoncesi 11:50, Satış
/molaaraligi 12:00-13:00, Satış
/molasonrasi 13:10, Satış
/mesaisonu 18:00, Satış
/kuralgoster Satış
/cagriaraligi 20, Satış

Excel notları:
- C sütunu: Arama saati
- E sütunu: Konuşma süresi
- F sütunu: Çaldırma süresi
- G sütunu: Personel adı, sadece 'isim-O' kayıtları dikkate alınır
- Departman, /yukle komutunda verilen değerden alınır
- /yukle <departman>, <HH:MM> komutu sadece o saate kadar görünen veriyi denetler
- /yukle <departman> <HH:MM> sonra komutu o saat ve sonrasındaki çalışmayı özetler
""".strip()

def _resolve_storage() -> Storage:
    database_path = os.getenv("DATABASE_PATH", "data/bot.db").strip() or "data/bot.db"
    return Storage(Path(database_path))


storage = _resolve_storage()
ARG_SPLIT_PATTERN = re.compile(r"\s*[|,]\s*")
MAX_TELEGRAM_MESSAGE_LENGTH = 3500


@dataclass(slots=True)
class UploadRequest:
    department: str
    control_time: str | None
    mode: Literal["violations", "after-hours"]


def _join_args(context: ContextTypes.DEFAULT_TYPE) -> str:
    return " ".join(context.args).strip()


def _pipe_args(text: str, expected_count: int) -> list[str]:
    pieces = [piece.strip() for piece in ARG_SPLIT_PATTERN.split(text) if piece.strip()]
    if len(pieces) != expected_count or any(not piece for piece in pieces):
        raise ValueError("Parametre formatı hatalı.")
    return pieces


def _validate_rule_values(
    max_wait_minutes: int,
    morning_latest: str,
    break_pre_leave: str,
    break_start: str,
    break_end: str,
    break_post_latest: str,
    shift_end: str,
) -> None:
    if max_wait_minutes <= 0:
        raise ValueError("Maksimum bekleme süresi 0'dan büyük olmalı.")

    morning_latest_dt = datetime.strptime(morning_latest, "%H:%M")
    break_pre_leave_dt = datetime.strptime(break_pre_leave, "%H:%M")
    break_start_dt = datetime.strptime(break_start, "%H:%M")
    break_end_dt = datetime.strptime(break_end, "%H:%M")
    break_post_latest_dt = datetime.strptime(break_post_latest, "%H:%M")
    shift_end_dt = datetime.strptime(shift_end, "%H:%M")

    if not morning_latest_dt < break_pre_leave_dt < break_start_dt < break_end_dt <= break_post_latest_dt <= shift_end_dt:
        raise ValueError(
            "Saat sıralaması hatalı. Şu düzen beklenir: sabah < mola öncesi < mola başlangıç < mola bitiş <= mola sonrası <= mesai sonu"
        )


def _build_rule(
    department: str,
    max_wait_minutes: int,
    morning_latest: str,
    break_pre_leave: str,
    break_start: str,
    break_end: str,
    break_post_latest: str,
    shift_end: str,
) -> DepartmentRule:
    _validate_rule_values(
        max_wait_minutes,
        morning_latest,
        break_pre_leave,
        break_start,
        break_end,
        break_post_latest,
        shift_end,
    )
    return DepartmentRule(
        department=normalize_department_name(department),
        max_wait_minutes=max_wait_minutes,
        morning_latest_start=morning_latest,
        break_pre_earliest_leave=break_pre_leave,
        break_start=break_start,
        break_end=break_end,
        break_post_latest_start=break_post_latest,
        shift_end_earliest_leave=shift_end,
    )


def _parse_rule_command(text: str) -> DepartmentRule:
    department, max_wait, morning_latest, break_pre_leave, break_range, break_post_latest, shift_end = _pipe_args(text, 7)
    if "-" not in break_range:
        raise ValueError("Mola aralığı '12:00-13:00' formatında olmalı.")

    break_start, break_end = [item.strip() for item in break_range.split("-", maxsplit=1)]
    return _build_rule(
        department,
        int(max_wait),
        morning_latest,
        break_pre_leave,
        break_start,
        break_end,
        break_post_latest,
        shift_end,
    )


def _parse_upload_command(text: str) -> UploadRequest:
    after_hours_match = re.match(
        r"^(?P<department>.+?)(?:\s*[|,]\s*|\s+)(?P<time>\d{2}:\d{2})\s+sonra$",
        text.strip(),
        re.IGNORECASE,
    )
    if after_hours_match:
        department = normalize_department_name(after_hours_match.group("department"))
        control_time = after_hours_match.group("time")
        datetime.strptime(control_time, "%H:%M")
        return UploadRequest(department=department, control_time=control_time, mode="after-hours")

    pieces = [piece.strip() for piece in ARG_SPLIT_PATTERN.split(text) if piece.strip()]
    if not pieces or len(pieces) > 2:
        raise ValueError("Kullanım: /yukle <departman> veya /yukle <departman>, <HH:MM> veya /yukle <departman> <HH:MM> sonra")

    department = normalize_department_name(pieces[0])
    control_time = None
    if len(pieces) == 2:
        datetime.strptime(pieces[1], "%H:%M")
        control_time = pieces[1]
    return UploadRequest(department=department, control_time=control_time, mode="violations")


def _get_existing_rule_or_raise(department: str) -> DepartmentRule:
    rule = storage.get_rule(department)
    if rule is None:
        raise ValueError("Bu departman için önce /kuralekle ile kural tanımlayın.")
    return rule


def _save_updated_rule(updated_rule: DepartmentRule) -> None:
    validated_rule = _build_rule(
        updated_rule.department,
        updated_rule.max_wait_minutes,
        updated_rule.morning_latest_start,
        updated_rule.break_pre_earliest_leave,
        updated_rule.break_start,
        updated_rule.break_end,
        updated_rule.break_post_latest_start,
        updated_rule.shift_end_earliest_leave,
    )
    storage.set_rule(validated_rule)


async def _send_chunked_text(update: Update, blocks: list[str]) -> None:
    if update.message is None:
        return

    current_parts: list[str] = []
    current_length = 0
    for block in blocks:
        block = block.strip()
        if not block:
            continue

        while len(block) > MAX_TELEGRAM_MESSAGE_LENGTH:
            if current_parts:
                await update.message.reply_text("\n\n".join(current_parts))
                current_parts = []
                current_length = 0
            await update.message.reply_text(block[:MAX_TELEGRAM_MESSAGE_LENGTH])
            block = block[MAX_TELEGRAM_MESSAGE_LENGTH:]

        if not block:
            continue

        separator_length = 2 if current_parts else 0
        if current_parts and current_length + separator_length + len(block) > MAX_TELEGRAM_MESSAGE_LENGTH:
            await update.message.reply_text("\n\n".join(current_parts))
            current_parts = [block]
            current_length = len(block)
        else:
            current_parts.append(block)
            current_length += separator_length + len(block)

    if current_parts:
        await update.message.reply_text("\n\n".join(current_parts))


async def start_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT)


async def department_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    department = _join_args(context)
    if not department:
        await update.message.reply_text("Kullanım: /departmanekle <departman>")
        return
    normalized_department = normalize_department_name(department)
    storage.add_department(normalized_department)
    await update.message.reply_text(f"Departman eklendi: {normalized_department}")


async def department_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    department = _join_args(context)
    if not department:
        await update.message.reply_text("Kullanım: /departmansil <departman>")
        return
    deleted = storage.delete_department(department)
    if deleted:
        await update.message.reply_text(f"Departman silindi: {normalize_department_name(department)}")
    else:
        await update.message.reply_text("Departman bulunamadı.")


async def department_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    departments = storage.list_departments()
    if not departments:
        await update.message.reply_text("Kayıtlı departman bulunmuyor.")
        return
    await _send_chunked_text(update, ["Kayıtlı departmanlar:\n" + "\n".join(f"- {item}" for item in departments)])


async def leave_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    person_name = _join_args(context)
    if not person_name:
        await update.message.reply_text("Kullanım: /izin <personel>")
        return
    normalized_display = " ".join(person_name.strip().split())
    storage.add_leave_person(normalized_display)
    await update.message.reply_text(f"İzin eklendi: {normalized_display}")


async def leave_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    person_name = _join_args(context)
    if not person_name:
        await update.message.reply_text("Kullanım: /izinsil <personel>")
        return
    deleted = storage.delete_leave_person(person_name)
    if deleted:
        await update.message.reply_text(f"İzin silindi: {normalize_person_name(person_name)}")
    else:
        await update.message.reply_text("Bu kişi için izin kaydı yok.")


async def leave_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    leave_people = storage.list_leave_people()
    if not leave_people:
        await update.message.reply_text("Kayıtlı izinli personel bulunmuyor.")
        return
    await _send_chunked_text(update, ["İzinli personeller:\n" + "\n".join(f"- {item}" for item in leave_people)])


async def supervisor_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        department, supervisor = _pipe_args(_join_args(context), 2)
    except ValueError:
        await update.message.reply_text("Kullanım: /sorumluekle <departman>, <sorumlu>")
        return
    storage.add_supervisor(department, supervisor)
    await update.message.reply_text(f"Sorumlu eklendi: {supervisor} / {normalize_department_name(department)}")


async def supervisor_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        department, supervisor = _pipe_args(_join_args(context), 2)
    except ValueError:
        await update.message.reply_text("Kullanım: /sorumlusil <departman>, <sorumlu>")
        return
    deleted = storage.delete_supervisor(department, supervisor)
    if deleted:
        await update.message.reply_text(f"Sorumlu silindi: {supervisor} / {normalize_department_name(department)}")
    else:
        await update.message.reply_text("Bu eşleşme bulunamadı.")


async def supervisor_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    department = _join_args(context)
    if not department:
        await update.message.reply_text("Kullanım: /sorumluliste <departman>")
        return

    supervisors = storage.get_supervisors(department)
    department_name = normalize_department_name(department)
    if not supervisors:
        await update.message.reply_text(f"{department_name} için kayıtlı sorumlu bulunamadı.")
        return

    await update.message.reply_text(
        f"{department_name} sorumluları:\n" + "\n".join(f"- {item}" for item in supervisors)
    )


async def rule_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        rule = _parse_rule_command(_join_args(context))
    except ValueError as exc:
        await update.message.reply_text(
            "Kullanım: /kuralekle <departman>, <max_bekleme_dk>, <sabah_en_gec>, <mola_oncesi_en_erken>, <mola_baslangic-mola_bitis>, <mola_sonrasi_en_gec>, <mesai_sonu_en_erken>\n"
            f"Hata: {exc}"
        )
        return
    storage.set_rule(rule)
    await update.message.reply_text(f"Kural kaydedildi: {rule.department}")


def _format_rule(rule: DepartmentRule) -> str:
    return "\n".join(
        [
            f"Departman: {rule.department}",
            f"Maksimum bekleme: {rule.max_wait_minutes} dk",
            f"Sabah en geç başlangıç: {rule.morning_latest_start}",
            f"Mola öncesi en erken bırakma: {rule.break_pre_earliest_leave}",
            f"Mola aralığı: {rule.break_start}-{rule.break_end}",
            f"Mola sonrası en geç başlangıç: {rule.break_post_latest_start}",
            f"Mesai sonu en erken bırakma: {rule.shift_end_earliest_leave}",
        ]
    )


async def rule_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    department = _join_args(context)
    if not department:
        await update.message.reply_text("Kullanım: /kuralgoster <departman>")
        return

    rule = storage.get_rule(department)
    if rule is None:
        await update.message.reply_text("Bu departman için kayıtlı kural bulunamadı.")
        return

    await update.message.reply_text(_format_rule(rule))


async def rule_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rules_map = storage.get_rules_map()
    if not rules_map:
        await update.message.reply_text("Kayıtlı kural bulunmuyor.")
        return

    await _send_chunked_text(update, [_format_rule(rule) for _, rule in sorted(rules_map.items())])


async def rule_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    department = _join_args(context)
    if not department:
        await update.message.reply_text("Kullanım: /kuralsil <departman>")
        return

    deleted = storage.delete_rule(department)
    if deleted:
        await update.message.reply_text(f"Kural silindi: {normalize_department_name(department)}")
    else:
        await update.message.reply_text("Bu departman için silinecek kural bulunamadı.")


async def call_gap_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        minutes_text, department = _pipe_args(_join_args(context), 2)
        minutes = int(minutes_text)
    except ValueError:
        await update.message.reply_text("Kullanım: /cagriaraligi <sure_dk>, <departman>")
        return

    if minutes <= 0:
        await update.message.reply_text("Çağrı aralığı süresi 0'dan büyük olmalı.")
        return

    updated = storage.update_max_wait_minutes(department, minutes)
    if not updated:
        await update.message.reply_text("Bu departman için önce /kuralekle ile kural tanımlayın.")
        return

    await update.message.reply_text(
        f"Çağrı aralığı güncellendi: {normalize_department_name(department)} / {minutes} dk"
    )


async def morning_latest_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        value, department = _pipe_args(_join_args(context), 2)
        datetime.strptime(value, "%H:%M")
        rule = _get_existing_rule_or_raise(department)
        _save_updated_rule(replace(rule, morning_latest_start=value))
    except ValueError as exc:
        await update.message.reply_text(f"Kullanım: /sabahengec <HH:MM>, <departman>\nHata: {exc}")
        return
    await update.message.reply_text(f"Sabah en geç başlangıç güncellendi: {normalize_department_name(department)} -> {value}")


async def break_pre_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        value, department = _pipe_args(_join_args(context), 2)
        datetime.strptime(value, "%H:%M")
        rule = _get_existing_rule_or_raise(department)
        _save_updated_rule(replace(rule, break_pre_earliest_leave=value))
    except ValueError as exc:
        await update.message.reply_text(f"Kullanım: /molaoncesi <HH:MM>, <departman>\nHata: {exc}")
        return
    await update.message.reply_text(f"Mola öncesi en erken bırakma güncellendi: {normalize_department_name(department)} -> {value}")


async def break_range_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        value, department = _pipe_args(_join_args(context), 2)
        if "-" not in value:
            raise ValueError("Mola aralığı '12:00-13:00' formatında olmalı.")
        break_start, break_end = [item.strip() for item in value.split("-", maxsplit=1)]
        datetime.strptime(break_start, "%H:%M")
        datetime.strptime(break_end, "%H:%M")
        rule = _get_existing_rule_or_raise(department)
        _save_updated_rule(replace(rule, break_start=break_start, break_end=break_end))
    except ValueError as exc:
        await update.message.reply_text(f"Kullanım: /molaaraligi <HH:MM-HH:MM>, <departman>\nHata: {exc}")
        return
    await update.message.reply_text(f"Mola aralığı güncellendi: {normalize_department_name(department)} -> {value}")


async def break_post_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        value, department = _pipe_args(_join_args(context), 2)
        datetime.strptime(value, "%H:%M")
        rule = _get_existing_rule_or_raise(department)
        _save_updated_rule(replace(rule, break_post_latest_start=value))
    except ValueError as exc:
        await update.message.reply_text(f"Kullanım: /molasonrasi <HH:MM>, <departman>\nHata: {exc}")
        return
    await update.message.reply_text(f"Mola sonrası en geç başlangıç güncellendi: {normalize_department_name(department)} -> {value}")


async def shift_end_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        value, department = _pipe_args(_join_args(context), 2)
        datetime.strptime(value, "%H:%M")
        rule = _get_existing_rule_or_raise(department)
        _save_updated_rule(replace(rule, shift_end_earliest_leave=value))
    except ValueError as exc:
        await update.message.reply_text(f"Kullanım: /mesaisonu <HH:MM>, <departman>\nHata: {exc}")
        return
    await update.message.reply_text(f"Mesai sonu en erken bırakma güncellendi: {normalize_department_name(department)} -> {value}")


async def status_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    summary = storage.get_status_summary()
    await update.message.reply_text(
        "\n".join(
            [
                "Bot durumu: Aktif",
                f"Departman sayısı: {summary['departments']}",
                f"Kural sayısı: {summary['rules']}",
                f"Sorumlu sayısı: {summary['supervisors']}",
                f"İzinli personel sayısı: {summary['leave_personnel']}",
                "Erişim: Gruptaki herkes kullanabilir",
            ]
        )
    )


async def upload_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        upload_request = _parse_upload_command(_join_args(context))
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    department = upload_request.department
    control_time = upload_request.control_time

    if storage.get_rule(department) is None:
        await update.message.reply_text("Bu departman için önce /kuralekle ile kural tanımlayın.")
        return

    context.user_data["awaiting_excel"] = True
    context.user_data["upload_department"] = department
    context.user_data["upload_control_time"] = control_time
    context.user_data["upload_mode_type"] = upload_request.mode
    if upload_request.mode == "after-hours":
        control_note = f"\nMesai sonrası özet saati: {control_time}\nBu saat ve sonrasındaki çağrılar için personel bazlı özet hazırlanacak."
    else:
        control_note = f"\nKontrol saati: {control_time}\nSadece bu saate kadar görünen veriler değerlendirilecek." if control_time else ""
    await update.message.reply_text(
        f"Departman seçildi: {department}{control_note}\nExcel dosyasını belge olarak gönderin."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document = update.message.document
    if document is None:
        return

    file_name = document.file_name or "rapor.xlsx"
    lower_name = file_name.lower()
    if not (lower_name.endswith(".xlsx") or lower_name.endswith(".xls")):
        await update.message.reply_text("Sadece Excel dosyaları işlenir.")
        return

    if not context.user_data.get("awaiting_excel"):
        await update.message.reply_text("Önce /yukle komutunu gönderin, sonra dosyayı yükleyin.")
        return

    upload_department = context.user_data.get("upload_department")
    upload_control_time = context.user_data.get("upload_control_time")
    upload_mode_type = context.user_data.get("upload_mode_type", "violations")
    context.user_data["awaiting_excel"] = False
    context.user_data.pop("upload_department", None)
    context.user_data.pop("upload_control_time", None)
    context.user_data.pop("upload_mode_type", None)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / file_name
        telegram_file = await context.bot.get_file(document.file_id)
        await telegram_file.download_to_drive(custom_path=str(temp_path))

        try:
            if upload_mode_type == "after-hours":
                summaries, inactive_people, warnings = summarize_after_hours_excel(
                    temp_path,
                    storage,
                    upload_department,
                    upload_control_time or "00:00",
                )
            else:
                results, missing_departments, report_path, warnings = analyze_excel(
                    temp_path,
                    storage,
                    upload_department,
                    upload_control_time,
                )
        except Exception as exc:
            logger.exception("Excel işlenemedi")
            await update.message.reply_text(f"Dosya işlenemedi: {exc}")
            return

        if upload_mode_type == "after-hours":
            for warning in warnings:
                await update.message.reply_text(warning)

            blocks: list[str] = []
            if summaries:
                for summary in summaries:
                    blocks.append(
                        "\n".join(
                            [
                                f"Tarih: {summary.report_date}",
                                f"Personel: {summary.person}",
                                f"Arama adedi: {summary.call_count}",
                                f"Toplam konuşma süresi: {summary.total_talk_duration}",
                            ]
                        )
                    )
            else:
                blocks.append(f"{upload_control_time} ve sonrası için çağrı kaydı bulunmadı.")

            for report_date, people in inactive_people.items():
                if not people:
                    continue
                blocks.append(
                    f"{report_date} / {upload_control_time} sonrası araması olmayanlar:\n" + "\n".join(f"- {person}" for person in people)
                )

            await _send_chunked_text(update, blocks)
            return

        if missing_departments:
            await update.message.reply_text(
                "Kuralı tanımlı olmayan departmanlar atlandı: " + ", ".join(missing_departments)
            )

        for warning in warnings:
            await update.message.reply_text(warning)

        if not results:
            await update.message.reply_text("İhlal bulunmadı.")
            return

        lines: list[str] = []
        for result in results[:20]:
            lines.append(
                "\n".join(
                    [
                        f"Personel: {result.person}",
                        "Kural ihlalleri:",
                        *[f"🔴 {item}" for item in result.violations],
                    ]
                )
            )
        if len(results) > 20:
            lines.append(f"Toplam {len(results)} personel analiz edildi. Tüm detaylar ekli Excel dosyasında.")

        await _send_chunked_text(update, lines)
        with report_path.open("rb") as report_file:
            await update.message.reply_document(document=report_file, filename=report_path.name)


async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Komut tanınmadı. Yardım için /help yazın.")


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN tanımlanmadı. .env dosyası oluşturun.")

    application = Application.builder().token(token).build()
    application.add_handler(CommandHandler("start", start_help))
    application.add_handler(CommandHandler("help", start_help))
    application.add_handler(CommandHandler("departmanekle", department_add))
    application.add_handler(CommandHandler("departmansil", department_delete))
    application.add_handler(CommandHandler("departmanliste", department_list))
    application.add_handler(CommandHandler("izin", leave_add))
    application.add_handler(CommandHandler("izinsil", leave_delete))
    application.add_handler(CommandHandler("izinliste", leave_list))
    application.add_handler(CommandHandler("sorumluekle", supervisor_add))
    application.add_handler(CommandHandler("sorumlusil", supervisor_delete))
    application.add_handler(CommandHandler("sorumluliste", supervisor_list))
    application.add_handler(CommandHandler("kuralekle", rule_add))
    application.add_handler(CommandHandler("sabahengec", morning_latest_update))
    application.add_handler(CommandHandler("molaoncesi", break_pre_update))
    application.add_handler(CommandHandler("molaaraligi", break_range_update))
    application.add_handler(CommandHandler("molasonrasi", break_post_update))
    application.add_handler(CommandHandler("mesaisonu", shift_end_update))
    application.add_handler(CommandHandler("kuralgoster", rule_show))
    application.add_handler(CommandHandler("kuralliste", rule_list))
    application.add_handler(CommandHandler("kuralsil", rule_delete))
    application.add_handler(CommandHandler("cagriaraligi", call_gap_update))
    application.add_handler(CommandHandler("durum", status_show))
    application.add_handler(CommandHandler("yukle", upload_mode))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
