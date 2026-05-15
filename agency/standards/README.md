# Agency Standards

Канонические документы агентства для генерации клиентских проектов через
AI Pipeline (`ai_agency/pipeline/`).

## Стандарты типов проектов

| Файл | Тип проекта | Sprint введения |
|---|---|---|
| `landing.md` | Лендинг (Next.js 15) | Sprint 3 (T-3-004) |
| `telegram_bot.md` | Telegram-бот | TODO Sprint v1.1 |
| `n8n.md` | n8n автоматизации | TODO Sprint v1.1 |
| `ai_assistant.md` | Внутренний AI-ассистент | TODO Sprint v1.1 |

Каждый стандарт описывает:
- Stack (LOCKED) — технологии и версии
- Folder structure
- Naming conventions
- Performance budget
- Что не использовать

При создании pipeline-run типа `landing` → Phase 3 (`architecture-decider`)
читает `landing.md` и применяет как basis для ARCHITECTURE.md проекта.

## Skill templates (`skills/`)

Phase 2/3/4 используют Claude skills. Skill files лежат **у пользователя** в
`~/.claude/skills/`, не в репо. Этот каталог содержит **templates** —
скопируйте их в `~/.claude/skills/<skill-name>/SKILL.md` для активации:

```bash
# Linux/macOS
mkdir -p ~/.claude/skills/prd-builder ~/.claude/skills/architecture-decider ~/.claude/skills/sprint-planner
cp agency/standards/skills/prd-builder.md       ~/.claude/skills/prd-builder/SKILL.md
cp agency/standards/skills/architecture-decider.md ~/.claude/skills/architecture-decider/SKILL.md
cp agency/standards/skills/sprint-planner.md    ~/.claude/skills/sprint-planner/SKILL.md
```

```powershell
# Windows
$skills = "$env:USERPROFILE\.claude\skills"
New-Item -ItemType Directory -Force -Path "$skills\prd-builder","$skills\architecture-decider","$skills\sprint-planner" | Out-Null
Copy-Item "agency\standards\skills\prd-builder.md"        "$skills\prd-builder\SKILL.md"
Copy-Item "agency\standards\skills\architecture-decider.md" "$skills\architecture-decider\SKILL.md"
Copy-Item "agency\standards\skills\sprint-planner.md"     "$skills\sprint-planner\SKILL.md"
```

После копирования — Claude Code сможет использовать скилы по invocation
`/prd-builder`, `/architecture-decider`, `/sprint-planner` внутри
pipeline-workspaces.
