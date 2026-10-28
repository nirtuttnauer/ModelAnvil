import type { Preview } from '@storybook/react-vite';
import { mswLoader } from 'msw-storybook-addon/csf3';
import { demoHandlers } from '../src/stories/demo-network';
import { setupWorker } from 'msw/browser';

const preview: Preview = {
  beforeEach() {
    if (!('__vitest_browser__' in globalThis)) return;
    // Storybook's _parent base target unloads the Vitest controller on native links.
    // Route links should navigate the preview document, as they do in the actual app.
    const base = document.querySelector('base');
    const target = base?.getAttribute('target');
    base?.setAttribute('target', '_self');
    return () => { if (target === null) base?.removeAttribute('target'); else if (target) base?.setAttribute('target', target); };
  },
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
