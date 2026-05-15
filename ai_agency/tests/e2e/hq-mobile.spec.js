const { test, expect } = require('@playwright/test');
const { loginHQ, boxesOverlap } = require('./helpers');

test.describe('Мобильный HQ (≤768px)', () => {
  test.beforeEach(async ({ page }) => {
    const vp = page.viewportSize();
    expect(vp.width).toBeLessThanOrEqual(768);
  });

  test('вход и мобильный хром: нижняя навигация, sidebar скрыт', async ({
    page,
  }) => {
    await loginHQ(page);
    await expect(page.locator('.mobile-bottom-nav')).toBeVisible();
    const sidebarDisplay = await page
      .locator('aside.sidebar')
      .evaluate((el) => getComputedStyle(el).display);
    expect(sidebarDisplay).toBe('none');
    await expect(page.locator('header.topbar')).toBeVisible();
  });

  test('дашборд: 4 метрики в сетке без перекрытий', async ({ page }) => {
    await loginHQ(page);
    const metrics = page.locator('.metric-card');
    await expect(metrics).toHaveCount(4, { timeout: 15000 });
    const cards = await metrics.all();
    const boxes = await Promise.all(cards.map((m) => m.boundingBox()));
    for (let i = 0; i < boxes.length; i++) {
      for (let j = i + 1; j < boxes.length; j++) {
        expect(boxesOverlap(boxes[i], boxes[j])).toBeFalsy();
      }
    }
  });

  test('нет горизонтального скролла у документа на дашборде', async ({
    page,
  }) => {
    await loginHQ(page);
    const overflow = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth > window.innerWidth,
      body: document.body.scrollWidth > window.innerWidth,
    }));
    expect(overflow.doc).toBeFalsy();
    expect(overflow.body).toBeFalsy();
  });

  test('нижняя навигация не перекрывает последнюю карточку метрик', async ({
    page,
  }) => {
    await loginHQ(page);
    const nav = page.locator('.mobile-bottom-nav');
    const lastMetric = page.locator('.metric-card').nth(3);
    await expect(nav).toBeVisible();
    const navBox = await nav.boundingBox();
    const metricBox = await lastMetric.boundingBox();
    expect(navBox && metricBox).toBeTruthy();
    expect(metricBox.y + metricBox.height).toBeLessThanOrEqual(navBox.y + 2);
  });

  test('быстрые действия: 4 плитки видны', async ({ page }) => {
    await loginHQ(page);
    await expect(page.locator('.hq-quick-tile')).toHaveCount(4);
  });

  test('переход в CRM через нижнее меню', async ({ page }) => {
    await loginHQ(page);
    await page.locator('.mobile-nav-item[data-page="crm"]').click();
    await expect(page).toHaveURL(/crm/i);
    await expect(page.getByRole('tab', { name: /клиенты/i })).toBeVisible();
  });

  test('переход в AI Команду через нижнее меню', async ({ page }) => {
    await loginHQ(page);
    await page.locator('.mobile-nav-item[data-page="team"]').click();
    await expect(page).toHaveURL(/team/i);
    await expect(page.locator('.agent-item').first()).toBeVisible({
      timeout: 15000,
    });
  });

  test('команда: выбор агента открывает чат-панель', async ({ page }) => {
    await loginHQ(page);
    await page.goto('/hq/team.html');
    await page.locator('.agent-item').first().click();
    await expect(page.locator('.chat-panel.open')).toBeVisible({
      timeout: 10000,
    });
    await expect(page.locator('#chatInput, .chat-input').first()).toBeVisible();
  });

  test('задача команде открывает bottom-sheet модал', async ({ page }) => {
    await loginHQ(page);
    await page.getByRole('button', { name: /задача команде/i }).click();
    await expect(page.locator('#add-task-modal')).toBeVisible();
    await expect(page.locator('#task-input')).toBeVisible();
  });

  test('аналитика: нет переполнения блока юнит-экономики', async ({
    page,
  }) => {
    await loginHQ(page);
    await page.goto('/hq/analytics.html');
    await page.locator('.aq-tab[data-aq="ue"]').click();
    const ue = page.locator('.unit-economics').first();
    await expect(ue).toBeVisible({ timeout: 15000 });
    const scrollWidth = await ue.evaluate((el) => el.scrollWidth);
    const clientWidth = await ue.evaluate((el) => el.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 8);
  });

  test('инструкция: нет горизонтального скролла и вкладки доступны', async ({
    page,
  }) => {
    await loginHQ(page);
    await page.goto('/hq/guide.html');
    await expect(page.locator('.guide-tabs-bar')).toBeVisible();
    await page.locator('.guide-tab[data-tab="metrics"]').click();
    await expect(page.locator('#panel-metrics')).toBeVisible();
    const overflow = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth,
      win: window.innerWidth,
    }));
    expect(overflow.doc).toBeLessThanOrEqual(overflow.win + 8);
  });

  test('аккаунт: быстрые кнопки видны после перехода с моб. меню', async ({
    page,
  }) => {
    await loginHQ(page);
    await page.locator('.mobile-nav-item[data-page="account"]').click();
    await expect(page).toHaveURL(/account/i);
    await expect(
      page.getByRole('button', { name: /ежедневный отчёт/i })
    ).toBeVisible();
  });
});
