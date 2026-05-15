"""
Настройки HQ: пресеты модели Claude (стоимость vs качество).
Хранятся в SQLite (app_settings). Telegram и фоновые задачи без HQ используют только CLAUDE_MODEL.
"""

from __future__ import annotations

import logging
import os

from database import get_app_setting, set_app_setting

logger = logging.getLogger("panel_settings")

KEY_PRESET = "hq_llm_preset"
KEY_CUSTOM = "hq_llm_custom_id"

VALID_PRESETS = frozenset({"economy", "balanced", "quality", "custom"})


def _balanced_model() -> str:
    return (os.getenv("CLAUDE_MODEL") or "").strip() or "claude-3-5-sonnet-20241022"


def preset_to_model_id() -> dict[str, str]:
    """ID моделей для API Anthropic; переопредели через .env при необходимости."""
    return {
        "economy": (os.getenv("HQ_MODEL_ECONOMY") or "").strip()
        or "claude-3-5-haiku-20241022",
        "balanced": _balanced_model(),
        "quality": (os.getenv("HQ_MODEL_QUALITY") or "").strip()
        or "claude-opus-4-1-20250805",
    }


async def get_resolved_hq_model_id() -> str:
    raw = await get_app_setting(KEY_PRESET)
    preset = (raw or "balanced").strip().lower()
    if preset not in VALID_PRESETS:
        preset = "balanced"
    pmap = preset_to_model_id()
    if preset == "custom":
        custom = (await get_app_setting(KEY_CUSTOM) or "").strip()
        if custom:
            return custom
        logger.warning("hq_llm_preset=custom, но hq_llm_custom_id пуст — balanced")
        return pmap["balanced"]
    return pmap.get(preset, pmap["balanced"])


def preset_descriptions_for_api() -> list[dict]:
    pmap = preset_to_model_id()
    return [
        {
            "id": "economy",
            "label": "Эконом",
            "hint": "Минимальная цена ответа, проще рассуждения",
            "model_id": pmap["economy"],
            "tier": 1,
        },
        {
            "id": "balanced",
            "label": "Баланс",
            "hint": "Как в CLAUDE_MODEL — основной режим",
            "model_id": pmap["balanced"],
            "tier": 2,
        },
        {
            "id": "quality",
            "label": "Качество",
            "hint": "Сильнее модель, дороже вход/выход",
            "model_id": pmap["quality"],
            "tier": 3,
        },
        {
            "id": "custom",
            "label": "Свой ID",
            "hint": "Любой доступный вам model id Anthropic",
            "model_id": "",
            "tier": 0,
        },
    ]


async def get_panel_settings_payload() -> dict:
    preset = (await get_app_setting(KEY_PRESET) or "balanced").strip().lower()
    if preset not in VALID_PRESETS:
        preset = "balanced"
    custom = (await get_app_setting(KEY_CUSTOM) or "").strip()
    resolved = await get_resolved_hq_model_id()
    return {
        "preset": preset,
        "custom_model_id": custom,
        "resolved_model_id": resolved,
        "presets": preset_descriptions_for_api(),
        "env_claude_model": _balanced_model(),
    }


async def save_panel_settings(preset: str, custom_model_id: str | None = None) -> dict:
    p = preset.strip().lower()
    if p not in VALID_PRESETS:
        raise ValueError(f"Неизвестный пресет: {preset}")
    if custom_model_id is not None:
        await set_app_setting(KEY_CUSTOM, custom_model_id.strip())
    if p == "custom":
        cm = (await get_app_setting(KEY_CUSTOM) or "").strip()
        if not cm:
            raise ValueError("Для «Свой ID» укажите custom_model_id (model id Anthropic)")
    await set_app_setting(KEY_PRESET, p)
    out = await get_panel_settings_payload()
    logger.info("Настройки HQ: preset=%s resolved=%s", out["preset"], out["resolved_model_id"])
    return out
