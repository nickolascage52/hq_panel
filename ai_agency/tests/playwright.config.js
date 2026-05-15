const path = require('path');
const fs = require('fs');
const { defineConfig, devices } = require('@playwright/test');

const agencyRoot = path.join(__dirname, '..');
const venvPythonWin = path.join(agencyRoot, 'venv', 'Scripts', 'python.exe');
const venvPythonUnix = path.join(agencyRoot, 'venv', 'bin', 'python');
const pythonExe = fs.existsSync(venvPythonWin)
  ? venvPythonWin
  : fs.existsSync(venvPythonUnix)
    ? venvPythonUnix
    : 'python';

module.exports = defineConfig({
  testDir: './e2e',
  timeout: 90000,
  expect: { timeout: 20000 },
  fullyParallel: true,
  reporter: [['html', { outputFolder: 'test-results' }], ['list']],
  projects: [
    {
      name: 'chromium-desktop',
      use: {
        baseURL: process.env.HQ_BASE_URL || 'http://127.0.0.1:8000',
        viewport: { width: 1280, height: 720 },
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',
      },
      testMatch: /hq\.spec\.js$/,
    },
    {
      name: 'mobile-chromium',
      use: {
        baseURL: process.env.HQ_BASE_URL || 'http://127.0.0.1:8000',
        ...devices['Pixel 5'],
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',
        hasTouch: true,
      },
      testMatch: /hq-mobile\.spec\.js$/,
    },
  ],
  webServer: process.env.HQ_SKIP_WEBSERVER
    ? undefined
    : {
        command: `"${pythonExe}" -m uvicorn main:app --host 127.0.0.1 --port 8000`,
        cwd: agencyRoot,
        url: 'http://127.0.0.1:8000/api/status',
        reuseExistingServer: !process.env.CI,
        timeout: 120000,
      },
});
