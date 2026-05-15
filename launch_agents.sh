#!/bin/bash
# Launch all AI Growth Team agents for Pixel Agents
# Run each command in a separate VS Code terminal

AGENTS=(
  "chief_of_staff:Chief of Staff"
  "content_strategist:Content Strategist"
  "telegram_lead:Telegram Lead"
  "threads_creator:Threads Creator"
  "vc_writer:VC Writer"
  "product_manager:Product Manager"
  "market_researcher:Market Researcher"
  "competitor_analyst:Competitor Analyst"
  "cro_ux:CRO/UX Analyst"
  "web_copywriter:Web Copywriter"
  "website_strategist:Website Strategist"
  "qa_agent:QA Agent"
)

echo "=== AI Growth Team - Pixel Agents Launcher ==="
echo ""
echo "Available agents:"
echo ""

for i in "${!AGENTS[@]}"; do
  IFS=':' read -r folder name <<< "${AGENTS[$i]}"
  echo "  $((i+1)). $name"
done

echo ""
echo "To launch an agent, run in a NEW terminal:"
echo ""

for agent in "${AGENTS[@]}"; do
  IFS=':' read -r folder name <<< "$agent"
  echo "claude --print \"Ты $name. Прочитай 01_AGENTS/$folder/SYSTEM_PROMPT.md и работай согласно этой роли.\""
  echo ""
done
