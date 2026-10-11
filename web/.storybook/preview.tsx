import type { Preview } from '@storybook/react-vite';
import { mswLoader } from 'msw-storybook-addon/csf3';
import { demoHandlers } from '../src/stories/demo-network';
import { setupWorker } from 'msw/browser';

const preview: Preview = {
  loaders: [mswLoader(async () => {
    const worker = setupWorker(...demoHandlers());
    await worker.start({ quiet: true, onUnhandledRequest: 'bypass' });
    return worker;
  })],
  parameters: {
    layout: 'fullscreen',
    controls: { disable: true },
    a11y: { test: 'error' },
    options: { storySort: { order: ['ModelAnvil', ['Screens', 'States']] } },
  },
};
export default preview;
