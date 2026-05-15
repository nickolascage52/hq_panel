#!/bin/bash
# Market Researcher
cd "$(dirname "$0")/.."
claude --print "Ты Market Researcher AI Growth команды. Прочитай свой системный промпт: 01_AGENTS/market_researcher/SYSTEM_PROMPT.md и работай согласно этой роли. Исследуй рынок и тренды."
