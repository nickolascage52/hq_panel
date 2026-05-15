#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "=== AI Delivery HQ — E2E Тесты ==="
echo "Убедись что сервер запущен на localhost:8000"
echo ""

if [ ! -d "node_modules" ]; then
  npm install
  npx playwright install chromium
fi

ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin2024}" npx playwright test --config=playwright.config.js "$@"

echo ""
echo "Результаты: откройте test-results/index.html"
