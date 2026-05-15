"""
Загрузка и хранение актуального контекста агентства.

Приоритет источников (от высшего к низшему):
1. Файл загруженный через веб-панель → data/agency_context.md
2. Файлы из старой структуры проекта  → 00_MASTER/*.md (если есть)
3. Дефолтный шаблон                  → встроенный текст-заглушка

Все агенты вызывают get_agency_context() — получают актуальный текст.
При загрузке нового файла через панель контекст обновляется без перезапуска.

Thread-safe: чтение файла происходит при каждом вызове, кэшируется на 60 секунд.
"""

import os
import sqlite3
import time
import logging
import threading
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("context_loader")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "data"
UPLOAD_PATH = UPLOAD_DIR / "agency_context.md"
DB_PATH = BASE_DIR / "agency.db"

PROJECT_ROOT = BASE_DIR.parent
LEGACY_CONTEXT = PROJECT_ROOT / "00_MASTER" / "AGENCY_CONTEXT.md"
LEGACY_TONE = PROJECT_ROOT / "00_MASTER" / "TONE_OF_VOICE.md"
LEGACY_OFFERS = PROJECT_ROOT / "00_MASTER" / "OFFERS.md"
LEGACY_MASTER = PROJECT_ROOT / "AGENCY_COPY_MASTER.md"

DEFAULT_CONTEXT = """
=== КОНТЕКСТ АГЕНТСТВА ===
Статус: НЕ ЗАПОЛНЕНО

Контекст агентства не загружен.
Загрузите файл с описанием агентства через HQ:
  → Откройте yourdomain.ru/hq/account.html
  → Блок «Контекст агентства»
  → Скачайте шаблон, заполните и загрузите

До загрузки агенты будут работать с минимальным контекстом.
=== КОНЕЦ КОНТЕКСТА ===
""".strip()

_cache_lock = threading.Lock()
_cached_context: str | None = None
_cached_at: float = 0
_cache_source: str = ""
CACHE_TTL = 60


def _read_file_safe(path: Path) -> str | None:
    """Прочитать файл, вернуть None если не существует или ошибка."""
    try:
        if path.exists() and path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception as e:
        logger.warning("Не удалось прочитать %s: %s", path, e)
    return None


def _build_legacy_context() -> str | None:
    """
    Собрать контекст из старых файлов 00_MASTER/.
    Объединяет AGENCY_CONTEXT.md + TONE_OF_VOICE.md + OFFERS.md.
    """
    parts = []

    ctx = _read_file_safe(LEGACY_CONTEXT)
    if ctx:
        parts.append(ctx)

    tone = _read_file_safe(LEGACY_TONE)
    if tone:
        parts.append(f"\n---\n\n{tone}")

    offers = _read_file_safe(LEGACY_OFFERS)
    if offers:
        parts.append(f"\n---\n\n{offers}")

    if not parts:
        master = _read_file_safe(LEGACY_MASTER)
        if master:
            return master

    return "\n".join(parts) if parts else None


def _knowledge_base_snippets() -> str:
    """Фрагменты из таблицы knowledge_base (status=ready), до 2000 симв. на файл."""
    if not DB_PATH.is_file():
        return ""
    try:
        con = sqlite3.connect(str(DB_PATH))
        cur = con.execute(
            """SELECT original_name, content_text FROM knowledge_base
               WHERE status = 'ready' AND COALESCE(content_text, '') != ''
               ORDER BY datetime(created_at) DESC LIMIT 40"""
        )
        rows = cur.fetchall()
        con.close()
    except sqlite3.Error as e:
        logger.debug("knowledge_base read: %s", e)
        return ""
    if not rows:
        return ""
    parts = ["\n\n=== БАЗА ЗНАНИЙ HQ (из загрузок) ==="]
    for name, txt in rows:
        chunk = (txt or "")[:2000]
        parts.append(f"\n--- {name} ---\n{chunk}")
    return "\n".join(parts)


def _resolve_context() -> tuple[str, str]:
    """Определить контекст по приоритету. Возвращает (text, source)."""

    uploaded = _read_file_safe(UPLOAD_PATH)
    if uploaded:
        return uploaded + _knowledge_base_snippets(), "uploaded"

    legacy = _build_legacy_context()
    if legacy:
        return legacy + _knowledge_base_snippets(), "legacy"

    return DEFAULT_CONTEXT + _knowledge_base_snippets(), "default"


def get_agency_context() -> str:
    """
    Возвращает актуальный контекст агентства.
    Кэшируется на 60 секунд для производительности.
    Thread-safe.
    """
    global _cached_context, _cached_at, _cache_source

    now = time.time()
    if _cached_context is not None and (now - _cached_at) < CACHE_TTL:
        return _cached_context

    with _cache_lock:
        if _cached_context is not None and (now - _cached_at) < CACHE_TTL:
            return _cached_context

        text, source = _resolve_context()
        _cached_context = text
        _cached_at = now
        _cache_source = source
        logger.debug("Контекст обновлён из источника: %s", source)
        return text


def invalidate_cache():
    """Сбросить кэш — контекст перечитается при следующем вызове."""
    global _cached_context, _cached_at, _cache_source
    with _cache_lock:
        _cached_context = None
        _cached_at = 0
        _cache_source = ""


def get_context_meta() -> dict:
    """Метаданные текущего контекста: источник, дата, размер."""
    text, source = _resolve_context()

    meta = {
        "source": source,
        "source_label": {
            "uploaded": "Загружен через панель",
            "legacy": "Из файлов проекта (00_MASTER/)",
            "default": "Шаблон по умолчанию (не заполнен)",
        }.get(source, source),
        "size_chars": len(text),
        "size_lines": text.count("\n") + 1,
    }

    if source == "uploaded" and UPLOAD_PATH.exists():
        stat = UPLOAD_PATH.stat()
        meta["uploaded_at"] = datetime.fromtimestamp(stat.st_mtime).isoformat()
        meta["filename"] = UPLOAD_PATH.name
    elif source == "legacy":
        meta["uploaded_at"] = None
        meta["filename"] = "00_MASTER/*.md"
    else:
        meta["uploaded_at"] = None
        meta["filename"] = None

    return meta


def save_uploaded_context(content: str, filename: str) -> dict:
    """
    Сохранить загруженный через панель файл.
    Валидация: только текст UTF-8, макс 500 КБ.
    Возвращает {success, message, preview}.
    """
    if not content or not content.strip():
        return {"success": False, "message": "Файл пустой", "preview": ""}

    size_bytes = len(content.encode("utf-8"))
    max_size = 500 * 1024
    if size_bytes > max_size:
        return {
            "success": False,
            "message": f"Файл слишком большой: {size_bytes // 1024} КБ (макс 500 КБ)",
            "preview": "",
        }

    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        backup_path = UPLOAD_DIR / f"agency_context.backup.{int(time.time())}.md"
        if UPLOAD_PATH.exists():
            UPLOAD_PATH.rename(backup_path)
            logger.info("Бэкап предыдущего контекста: %s", backup_path.name)

        UPLOAD_PATH.write_text(content, encoding="utf-8")

        invalidate_cache()

        preview = content.strip()[:300]
        logger.info(
            "Контекст агентства обновлён: %s (%d символов, из файла '%s')",
            UPLOAD_PATH, len(content), filename,
        )
        return {
            "success": True,
            "message": f"Файл '{filename}' загружен ({len(content)} символов). Все агенты используют новый контекст.",
            "preview": preview,
        }

    except Exception as e:
        logger.error("Ошибка сохранения контекста: %s", e, exc_info=True)
        return {
            "success": False,
            "message": f"Ошибка записи: {str(e)}",
            "preview": "",
        }


def get_context_preview(chars: int = 500) -> str:
    """Первые N символов текущего контекста для превью в панели."""
    text = get_agency_context()
    if len(text) <= chars:
        return text
    return text[:chars].rsplit("\n", 1)[0] + "\n..."
