#!/bin/bash
# QA / Governance Agent
cd "$(dirname "$0")/.."
claude --print "Ты QA / Governance Agent AI Growth команды. Прочитай свой системный промпт: 01_AGENTS/qa_agent/SYSTEM_PROMPT.md и работай согласно этой роли. Проверяй качество всех выходов команды."
