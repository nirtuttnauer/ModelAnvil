import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, within } from 'storybook/test';
import { ModelHardwareFit } from '../components/ModelHardwareFit';
import type { HardwareTarget, ModelMemory } from '../api/model-hardware';
import '../style.css';
import './data-inspector-stories.css';

const gib = 1024**3;
const profile = { host_memory_bytes: 8 * gib, accelerator_memory_bytes: 4 * gib, accelerator_backends: ['cuda', 'mps'],
  runtime_contract: 'storybook-training-contract', basis: 'Fictional profile minimum for UI testing. Preflight still checks live headroom and exact inputs.' };
const memory: ModelMemory = { weights_bytes: gib, training: profile };
const target: HardwareTarget = { id: 'one', name: 'Research GPU · Demo', hostBytes: 16 * gib, acceleratorBytes: 8 * gib,
  backend: 'cuda', runtimeContract: profile.runtime_contract, connected: true, busy: false, observedAt: Date.now(), maxAgeSeconds: 60 };
const meta = {
  title: 'ModelAnvil/Components/Model hardware', component: ModelHardwareFit,
  args: { memory, targets: [target] }, parameters: { layout: 'fullscreen' },
  beforeEach({ parameters }) {
    document.documentElement.dataset.theme = parameters.demoTheme ?? 'light';
    delete document.getElementById('storybook-root')?.dataset.demoVerified;
  },
  decorators: [(Story) => <div className="data-story-canvas"><p className="muted">DEMO · Fictional hardware declarations</p><Story /></div>],
} satisfies Meta<typeof ModelHardwareFit>;
export default meta;
type Story = StoryObj<typeof meta>;
const check = (name: string): Story['play'] => async ({ canvasElement }) => {
  await expect(within(canvasElement).getByText(name, { exact: true })).toBeVisible();
  canvasElement.dataset.demoVerified = 'passed';
};
export const MemoryFits: Story = { play: check('Meets declared memory minimum') };
export const TooLarge: Story = { args: { targets: [{ ...target, hostBytes: 4 * gib, acceleratorBytes: 2 * gib }] }, play: check('Memory minimum not met') };
export const UnknownAccelerator: Story = { args: { targets: [{ ...target, backend: 'mps', acceleratorBytes: null }] }, play: check('Host memory fits · accelerator memory unknown') };
export const Stale: Story = { args: { targets: [{ ...target, observedAt: Date.now() - 61000 }] }, play: check('Hardware report unavailable') };
export const Busy: Story = { args: { targets: [{ ...target, busy: true }] }, play: check('The worker is busy. Memory fit does not mean an execution slot is free.') };
export const UnknownSnapshot: Story = { args: { memory: { weights_bytes: 4 * gib, training: null } }, play: check('Hardware fit unknown') };
export const Unsupported: Story = { args: { compatible: false, reason: 'This model does not support the selected recipe.' }, play: check('Training compatibility unavailable') };
export const Dark: Story = { ...MemoryFits, parameters: { demoTheme: 'dark' } };
export const Preview: Story = {};
