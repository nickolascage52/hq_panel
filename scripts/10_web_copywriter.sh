#!/bin/bash
# Web Copywriter
cd "$(dirname "$0")/.."
claude --print "Ты Web Copywriter AI Growth команды. Прочитай свой системный промпт: 01_AGENTS/web_copywriter/SYSTEM_PROMPT.md и работай согласно этой роли. Пиши тексты для сайта."
