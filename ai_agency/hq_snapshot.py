"""JSON-снимок данных для Аккаунт-менеджера (API и Telegram)."""

import json
from datetime import date

from database import (
    get_clients,
    get_projects,
    get_students,
    get_deadlines,
    get_business_metrics,
    get_reminders_due,
)


async def build_account_snapshot_json() -> str:
    clients = await get_clients()
    projects = await get_projects()
    students = await get_students()
    dl = await get_deadlines(14)
    bm = await get_business_metrics()
    today = date.today().isoformat()
    rem_open = await get_reminders_due(include_sent=False)
    rem_today = [
        r for r in rem_open
        if r.get("scheduled_for") and str(r["scheduled_for"])[:10] == today
    ]
    balances = []
    for c in clients:
        ta = float(c.get("total_amount") or 0)
        pa = float(c.get("paid_amount") or 0)
        if ta > pa:
            balances.append({
                "client_id": c["id"],
                "name": c.get("name"),
                "balance": ta - pa,
                "status": c.get("status"),
            })
    bundle = {
        "date_today": today,
        "weekday_mon0": date.today().weekday(),
        "calendar_note": "По процессу владельца: ежедневные напоминания все дни кроме четверга; по явному запросу отвечай всегда.",
        "clients": clients,
        "projects": projects,
        "students": students,
        "deadlines_next_14_days": dl,
        "business_metrics": bm,
        "reminders_open": rem_open[:80],
        "reminders_for_today": rem_today,
        "client_balances": balances,
    }
    return json.dumps(bundle, ensure_ascii=False, default=str)
