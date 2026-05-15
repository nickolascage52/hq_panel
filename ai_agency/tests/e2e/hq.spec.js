const { test, expect } = require('@playwright/test');
const { PASSWORD, loginHQ } = require('./helpers');

async function login(page) {
  await loginHQ(page);
  await expect(page.locator('.sidebar')).toBeVisible({ timeout: 10000 });
}

test.describe('Авторизация', () => {
  test('показывает экран входа', async ({ page }) => {
    await page.goto('/hq/');
    await expect(page.locator('input[type="password"]')).toBeVisible();
  });

  test('неверный пароль показывает ошибку', async ({ page }) => {
    await page.goto('/hq/');
    await page.locator('input[type="password"]').fill('wrongpassword-xyz');
    await page.getByRole('button', { name: /войти/i }).click();
    await expect(
      page.locator('.error-msg, .toast, #authErr, [class*="error"]')
    ).toBeVisible({ timeout: 5000 });
  });

  test('верный пароль открывает дашборд', async ({ page }) => {
    await login(page);
    await expect(page.locator('.sidebar')).toBeVisible();
    await expect(page.locator('.hq-content[data-page="dashboard"]')).toBeVisible();
  });
});

test.describe('Дашборд', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('показывает 4 метрики', async ({ page }) => {
    const metrics = page.locator('.metric-card');
    await expect(metrics).toHaveCount(4, { timeout: 10000 });
  });

  test('метрики не перекрывают друг друга', async ({ page }) => {
    const cards = await page.locator('.metric-card').all();
    const boxes = await Promise.all(cards.map((m) => m.boundingBox()));
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        if (!boxes[i] || !boxes[j]) continue;
        const overlap =
          boxes[i].x < boxes[j].x + boxes[j].width &&
          boxes[i].x + boxes[i].width > boxes[j].x &&
          boxes[i].y < boxes[j].y + boxes[j].height &&
          boxes[i].y + boxes[i].height > boxes[j].y;
        expect(overlap).toBeFalsy();
      }
    }
  });

  test('кнопка задача команде открывает модал', async ({ page }) => {
    await page
      .getByRole('button', { name: /задача команде/i })
      .click();
    await expect(page.locator('#add-task-modal.modal-backdrop')).toBeVisible();
  });

  test('контент дашборда без вертикального скролла у body', async ({ page }) => {
    const bodyScrollHeight = await page.evaluate(() => document.body.scrollHeight);
    const viewportHeight = page.viewportSize().height;
    expect(bodyScrollHeight).toBeLessThanOrEqual(viewportHeight + 8);
  });
});

test.describe('CRM', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/hq/crm.html');
  });

  test('открывается страница CRM', async ({ page }) => {
    await expect(page.locator('body')).toBeVisible();
    expect(page.url()).toContain('/crm');
  });

  test('таб Клиенты активен по умолчанию', async ({ page }) => {
    await expect(page.getByRole('tab', { name: /клиенты/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /клиенты/i })).toHaveAttribute(
      'aria-selected',
      'true'
    );
  });

  test('переключение на таб Ученики', async ({ page }) => {
    await page.getByRole('tab', { name: /ученики/i }).click();
    await expect(page.locator('#students-tab, [data-tab="students"]')).toBeVisible();
  });

  test('кнопка добавить клиента открывает форму', async ({ page }) => {
    await page.getByRole('button', { name: /\+ клиент|добавить клиента/i }).click();
    await expect(page.locator('#mCli.is-open')).toBeVisible();
    await expect(page.locator('#mCli input, #mCli select, #mCli textarea').first()).toBeVisible();
  });

  test('ячейки таблицы с переполнением используют ellipsis', async ({ page }) => {
    const cells = await page.locator('#tblC td').all();
    const slice = cells.slice(0, Math.min(10, cells.length));
    for (const cell of slice) {
      const overflow = await cell.evaluate((el) => {
        const style = window.getComputedStyle(el);
        return el.scrollWidth > el.clientWidth && style.overflow !== 'hidden';
      });
      if (overflow) {
        const textOverflow = await cell.evaluate((el) =>
          window.getComputedStyle(el).textOverflow
        );
        expect(textOverflow).toBe('ellipsis');
      }
    }
  });
});

test.describe('AI Команда', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/hq/team.html');
  });

  test('список агентов отображается', async ({ page }) => {
    await expect(page.locator('.agent-item').first()).toBeVisible({ timeout: 10000 });
  });

  test('клик на агента открывает чат', async ({ page }) => {
    await page.locator('.agent-item').first().click();
    await expect(
      page.locator('.chat-input, textarea[placeholder*="Сообщение"], textarea[placeholder*="сообщение"]')
    ).toBeVisible();
  });

  test('поле ввода присутствует', async ({ page }) => {
    await page.locator('.agent-item').first().click();
    const input = page.locator('#chatInput, .chat-input, textarea').first();
    await expect(input).toBeVisible();
    await expect(input).toBeEditable();
  });
});

test.describe('Аналитика', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/hq/analytics.html');
  });

  test('вкладка Обзор: таблица метрик из API', async ({ page }) => {
    await expect(page.locator('#overviewMetricsTbody')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('#overviewMetricsTbody tr')).toHaveCount(10, { timeout: 15000 });
  });

  test('вкладка Финансы: карточки и P&L', async ({ page }) => {
    await page.locator('.aq-tab[data-aq="fin"]').click();
    await expect(page.locator('#aq-fin .analytics-card')).toHaveCount(3, { timeout: 10000 });
    await expect(page.locator('#plTbody')).toBeVisible();
  });

  test('юнит-экономика: поля ввода работают', async ({ page }) => {
    await page.locator('.aq-tab[data-aq="ue"]').click();
    const revenueInput = page.locator('#ue_revenue_fact');
    await expect(revenueInput).toBeVisible();
    await revenueInput.fill('750000');
    await expect(page.locator('#ue_profit')).not.toHaveText('');
  });

  test('юнит-экономика: нет горизонтального скролла', async ({ page }) => {
    await page.locator('.aq-tab[data-aq="ue"]').click();
    const ueBlock = page.locator('.unit-economics').first();
    await expect(ueBlock).toBeVisible();
    const scrollWidth = await ueBlock.evaluate((el) => el.scrollWidth);
    const clientWidth = await ueBlock.evaluate((el) => el.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 5);
  });

  test('страница без лишнего скролла документа', async ({ page }) => {
    const scrollHeight = await page.evaluate(() => document.documentElement.scrollHeight);
    const clientHeight = await page.evaluate(() => window.innerHeight);
    expect(scrollHeight).toBeLessThanOrEqual(clientHeight + 12);
  });
});

test.describe('Инструкция', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/hq/guide.html');
  });

  test('вкладки инструкции отображаются и переключаются', async ({ page }) => {
    await expect(page.locator('.guide-tabs-bar')).toBeVisible();
    await page.locator('.guide-tab[data-tab="metrics"]').click();
    await expect(page.locator('#panel-metrics')).toBeVisible();
    await page.locator('.guide-tab[data-tab="notes"]').click();
    await expect(page.locator('#panel-notes')).toBeVisible();
  });

  test('контейнер инструкции прокручивается до конца', async ({ page }) => {
    const wrap = page.locator('.hq-guide-wrap');
    await expect(wrap).toBeVisible();
    await wrap.evaluate((el) => { el.scrollTop = el.scrollHeight; });
    const pos = await wrap.evaluate((el) => ({
      top: el.scrollTop,
      max: el.scrollHeight - el.clientHeight,
    }));
    expect(pos.top).toBeGreaterThanOrEqual(Math.max(0, pos.max - 8));
  });
});

test.describe('Аккаунт-менеджер', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto('/hq/account.html');
  });

  test('кнопки быстрых действий присутствуют', async ({ page }) => {
    await expect(page.getByRole('button', { name: /отчёт/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /клиенты/i })).toBeVisible();
  });

  test('кнопка ежедневного отчёта запускает запрос', async ({ page }) => {
    const responsePromise = page.waitForResponse(
      (res) => res.url().includes('/api/account-manager'),
      { timeout: 30000 }
    );
    await page.getByRole('button', { name: /ежедневный отчёт/i }).click();
    await responsePromise;
    await expect(page.locator('.report-content, #out')).toBeVisible({ timeout: 20000 });
  });
});

test.describe('UX/UI качество', () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test('sidebar навигация совпадает на ключевых страницах', async ({ page }) => {
    const urls = ['/hq/', '/hq/crm.html', '/hq/team.html', '/hq/analytics.html'];
    let firstSig = null;
    for (const url of urls) {
      await page.goto(url);
      const sig = await page.evaluate(() => {
        const links = Array.from(document.querySelectorAll('.sidebar nav a'));
        return links
          .map((a) => (a.getAttribute('href') || '') + '\t' + a.textContent.replace(/\s+/g, ' ').trim())
          .join('\n');
      });
      if (firstSig === null) firstSig = sig;
      else expect(sig).toBe(firstSig);
    }
  });

  test('основные кнопки с cursor:pointer', async ({ page }) => {
    await page.goto('/hq/');
    const buttons = await page.locator('button').all();
    for (const btn of buttons.slice(0, 20)) {
      const cursor = await btn.evaluate((el) => window.getComputedStyle(el).cursor);
      expect(cursor).toBe('pointer');
    }
  });

  test('дашборд без горизонтального скролла', async ({ page }) => {
    await page.goto('/hq/');
    const hasHScroll = await page.evaluate(
      () => document.documentElement.scrollWidth > window.innerWidth
    );
    expect(hasHScroll).toBeFalsy();
  });

  test('время в topbar обновляется', async ({ page }) => {
    await page.goto('/hq/');
    const clock = page.locator('.topbar-time, #hqClock');
    const time1 = await clock.textContent();
    await page.waitForTimeout(1600);
    const time2 = await clock.textContent();
    expect(time1).not.toBe(time2);
  });
});
