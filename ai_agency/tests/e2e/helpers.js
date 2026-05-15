const { expect } = require('@playwright/test');

const PASSWORD = process.env.ADMIN_PASSWORD || 'Admin2024';

/** Вход в HQ; ждём контент дашборда (работает и на мобиле без sidebar). */
async function loginHQ(page) {
  await page.goto('/hq/');
  const passwordInput = page.locator('input[type="password"]');
  if (await passwordInput.isVisible()) {
    await passwordInput.fill(PASSWORD);
    await page.getByRole('button', { name: /войти/i }).click();
  }
  await expect(page.locator('.metric-card').first()).toBeVisible({ timeout: 20000 });
}

/** Проверка, что два прямоугольника не пересекаются. */
function boxesOverlap(a, b) {
  if (!a || !b) return false;
  return (
    a.x < b.x + b.width &&
    a.x + a.width > b.x &&
    a.y < b.y + b.height &&
    a.y + a.height > b.y
  );
}

module.exports = { PASSWORD, loginHQ, boxesOverlap };
