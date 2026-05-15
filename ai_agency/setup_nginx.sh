#!/bin/bash
set -e

echo ""
echo "════════════════════════════════════════════"
echo "  AI Agency — Настройка Nginx"
echo "════════════════════════════════════════════"
echo ""

ADDITION_CONF="/var/www/ai_agency/nginx_addition.conf"

if [ ! -f "$ADDITION_CONF" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    ADDITION_CONF="$SCRIPT_DIR/nginx_addition.conf"
fi

if [ ! -f "$ADDITION_CONF" ]; then
    echo "❌ Файл nginx_addition.conf не найден"
    echo "   Ожидается: /var/www/ai_agency/nginx_addition.conf"
    exit 1
fi

echo "📄 Location блоки: $ADDITION_CONF"
echo ""

# ── Поиск конфига nginx для сайта ──

NGINX_CONF=""
SEARCH_DIRS=("/etc/nginx/sites-enabled" "/etc/nginx/conf.d" "/etc/nginx/vhosts")

for dir in "${SEARCH_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        for conf in "$dir"/*.conf "$dir"/*; do
            [ -f "$conf" ] || continue
            # Пропускаем дефолтный конфиг и фрагменты
            basename=$(basename "$conf")
            if [[ "$basename" == "default" || "$basename" == "default.conf" ]]; then
                continue
            fi
            # Ищем файл с server {} блоком и listen 443/80
            if grep -q "server_name" "$conf" 2>/dev/null; then
                if grep -q "listen" "$conf" 2>/dev/null; then
                    NGINX_CONF="$conf"
                    break 2
                fi
            fi
        done
    fi
done

if [ -z "$NGINX_CONF" ]; then
    echo "⚠️  Не удалось автоматически найти конфиг nginx для сайта."
    echo ""
    echo "   Стандартные места:"
    echo "   - /etc/nginx/sites-enabled/yourdomain.conf"
    echo "   - /etc/nginx/conf.d/yourdomain.conf"
    echo "   - /etc/nginx/vhosts/yourdomain.conf (ISPmanager)"
    echo ""
    echo "   Найди вручную: nginx -T 2>/dev/null | grep 'server_name' "
    echo ""
    read -p "   Введи полный путь к конфигу: " NGINX_CONF
    if [ ! -f "$NGINX_CONF" ]; then
        echo "❌ Файл не найден: $NGINX_CONF"
        exit 1
    fi
fi

echo "✅ Найден конфиг: $NGINX_CONF"
echo ""

# ── Проверка: уже добавлено? ──

if grep -q "ai_agency" "$NGINX_CONF" 2>/dev/null; then
    echo "⚠️  Похоже, AI Agency location блоки уже добавлены в этот конфиг."
    read -p "   Продолжить всё равно? (y/N): " CONTINUE
    if [[ "$CONTINUE" != "y" && "$CONTINUE" != "Y" ]]; then
        echo "Отменено."
        exit 0
    fi
fi

# ── Резервная копия ──

BACKUP="${NGINX_CONF}.backup.$(date +%Y%m%d_%H%M%S)"
cp "$NGINX_CONF" "$BACKUP"
echo "💾 Резервная копия: $BACKUP"

# ── Вставка location блоков ──
# Ищем последнюю закрывающую скобку } в файле (конец server блока)
# и вставляем наши location блоки перед ней.

ADDITION_CONTENT=$(cat "$ADDITION_CONF")

# Находим номер последней строки с } в файле
LAST_BRACE_LINE=$(grep -n "^}" "$NGINX_CONF" | tail -1 | cut -d: -f1)

if [ -z "$LAST_BRACE_LINE" ]; then
    echo "❌ Не удалось найти закрывающую скобку } в конфиге."
    echo "   Возможно, конфиг имеет нестандартный формат."
    echo "   Добавь содержимое nginx_addition.conf вручную."
    cp "$BACKUP" "$NGINX_CONF"
    exit 1
fi

# Разделяем файл: до последней }, добавляем наши блоки, затем }
head -n $((LAST_BRACE_LINE - 1)) "$NGINX_CONF" > "${NGINX_CONF}.tmp"
echo "" >> "${NGINX_CONF}.tmp"
echo "$ADDITION_CONTENT" >> "${NGINX_CONF}.tmp"
echo "" >> "${NGINX_CONF}.tmp"
tail -n +"$LAST_BRACE_LINE" "$NGINX_CONF" >> "${NGINX_CONF}.tmp"
mv "${NGINX_CONF}.tmp" "$NGINX_CONF"

echo "✅ Location блоки добавлены в конфиг"
echo ""

# ── Проверка конфига ──

echo "🔍 Проверка конфигурации nginx..."
if nginx -t 2>&1; then
    echo ""
    echo "✅ Конфигурация корректна"
else
    echo ""
    echo "❌ Ошибка в конфигурации nginx!"
    echo "   Восстанавливаю из резервной копии..."
    cp "$BACKUP" "$NGINX_CONF"
    echo "   Конфиг восстановлен. Проверь nginx_addition.conf вручную."
    exit 1
fi

# ── Перезагрузка nginx ──

echo "🔄 Перезагрузка nginx..."
systemctl reload nginx
echo "✅ Nginx перезагружен"

echo ""
echo "════════════════════════════════════════════"
echo "  ✅ Nginx настроен!"
echo "════════════════════════════════════════════"
echo ""
echo "  HQ:     https://yourdomain.ru/hq/"
echo "  API:    https://yourdomain.ru/api/status"
echo ""
echo "  Резервная копия: $BACKUP"
echo "  Откат: cp $BACKUP $NGINX_CONF && nginx -t && systemctl reload nginx"
echo ""
