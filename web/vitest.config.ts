import { defineConfig } from 'vitest/config';
import { storybookTest } from '@storybook/addon-vitest/vitest-plugin';
import { playwright } from '@vitest/browser-playwright';
import viteConfig from './vite.config.ts';

export default defineConfig({
  ...viteConfig,
  server: { ...viteConfig.server, proxy: {} },
  plugins: [...(viteConfig.plugins ?? []), storybookTest({ configDir: '.storybook' })],
  test: {
    name: 'storybook',
    maxWorkers: 1,
    testTimeout: 30_000,
    browser: {
      enabled: true,
      headless: true,
      provider: playwright(),
      instances: [{ browser: 'chromium' }],
    },
  },
});
