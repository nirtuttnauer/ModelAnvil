import type { StorybookConfig } from '@storybook/react-vite';

const config: StorybookConfig = {
  stories: ['../src/stories/**/*.stories.tsx'],
  addons: ['@storybook/addon-a11y', 'msw-storybook-addon'],
  framework: '@storybook/react-vite',
  staticDirs: ['../public', './static'],
  core: { disableTelemetry: true },
  async viteFinal(config) {
    // Demo actions must never be forwarded to the application's backend.
    return { ...config, server: { ...config.server, proxy: {} } };
  },
};
export default config;
