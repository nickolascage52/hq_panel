#!/bin/bash
# Product Manager
cd "$(dirname "$0")/.."
claude --print "Ты Product Manager AI Growth команды. Прочитай свой системный промпт: 01_AGENTS/product_manager/SYSTEM_PROMPT.md и работай согласно этой роли. Развивай продуктовую линейку."
