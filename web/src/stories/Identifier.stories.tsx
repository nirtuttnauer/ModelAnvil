import type { Meta, StoryObj } from '@storybook/react-vite';
import { useEffect, useRef } from 'react';
import { expect, fn, userEvent, waitFor, within } from 'storybook/test';
import { Identifier } from '../components/Identifier';
import '../design-system/index.css';

const value = '019a3621-4d78-7bd0-8e43-9a091242336a';
let write = fn(async (_value: string) => {});
let completeCopy: (() => void) | undefined;
const meta = {
  title: 'ModelAnvil/Components/Identifier', component: Identifier, args: { value },
  parameters: { layout: 'fullscreen' },
  beforeEach({ parameters }) {
    document.documentElement.dataset.theme = parameters.demoTheme ?? 'light';
    delete document.getElementById('storybook-root')?.dataset.demoVerified;
    const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
    completeCopy = undefined;
    write = fn(async (_text: string) => {});
    if (parameters.clipboardPending) write.mockImplementation(() => new Promise<void>(resolve => { completeCopy = resolve; }));
    if (parameters.clipboardFailure) write.mockRejectedValue(new Error('Clipboard denied'));
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: write } });
    return () => {
      completeCopy?.();
      if (original) Object.defineProperty(navigator, 'clipboard', original);
      else Reflect.deleteProperty(navigator, 'clipboard');
    };
  },
  decorators: [(Story) => <main style={{ minHeight: 450, padding: '240px 24px 24px' }}><Story /></main>],
} satisfies Meta<typeof Identifier>;
export default meta;
type Story = StoryObj<typeof meta>;
const tooltip = () => within(document.body).getByRole('tooltip');

export const HoverAndCopy: Story = {
  name: 'Hover exact ID and copy only after clipboard succeeds',
  parameters: { clipboardPending: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement), button = canvas.getByRole('button', { name: 'Copy ID' });
    await expect(canvas.queryByText(value)).not.toBeInTheDocument();
    await expect(canvas.getByRole('status')).toBeEmptyDOMElement();
    await userEvent.hover(button);
    await waitFor(() => expect(tooltip()).toHaveAttribute('data-side', 'above'));
    await expect(within(tooltip()).getByText(value, { selector: 'code' })).toBeVisible();
    await expect(button).toHaveAttribute('aria-describedby', tooltip().id);
    await userEvent.click(button);
    await expect(write).toHaveBeenCalledWith(value);
    await expect(canvas.getByRole('status')).toBeEmptyDOMElement();
    await expect(within(tooltip()).queryByText('ID · Copied')).not.toBeInTheDocument();
    completeCopy?.();
    await waitFor(() => expect(canvas.getByRole('status')).toHaveTextContent('ID copied.'));
    await expect(within(tooltip()).getByText('ID · Copied')).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const KeyboardFocusAndCopy: Story = {
  name: 'Keyboard focus reveals ID, Escape dismisses, Enter copies',
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement), button = canvas.getByRole('button', { name: 'Copy ID' });
    await userEvent.tab();
    await expect(button).toHaveFocus();
    await expect(within(await within(document.body).findByRole('tooltip')).getByText(value)).toBeVisible();
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(within(document.body).queryByRole('tooltip')).not.toBeInTheDocument());
    await expect(button).toHaveFocus();
    await expect(button).not.toHaveAttribute('aria-describedby');
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(write).toHaveBeenCalledWith(value));
    await expect(canvas.getByRole('status')).toHaveTextContent('ID copied.');
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ClipboardFailure: Story = {
  name: 'Clipboard failure retains exact value for manual copy',
  parameters: { clipboardFailure: true },
  args: { label: 'Model ID' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Copy Model ID' }));
    await waitFor(() => expect(canvas.getByRole('status')).toHaveTextContent('Could not copy Model ID.'));
    await expect(write).toHaveBeenCalledWith(value);
    await expect(canvas.getByRole('status')).not.toHaveTextContent('Model ID copied.');
    await expect(within(tooltip()).getByText('Copy unavailable. Select this value to copy manually.')).toBeVisible();
    await expect(within(tooltip()).getByText(value, { selector: 'code' })).toBeVisible();
    await expect(getComputedStyle(tooltip()).userSelect).toBe('text');
    await expect(within(tooltip()).queryByText('Model ID · Copied')).not.toBeInTheDocument();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ViewportEdgesAndOverflow: Story = {
  name: 'Tooltip escapes clipping containers and stays within viewport edges',
  render: () => <>
    <div data-testid="top-container" style={{ position: 'fixed', left: 8, top: 8, width: 64, height: 40, overflow: 'hidden' }}><Identifier value={value} label="Top edge ID" /></div>
    <div style={{ position: 'fixed', right: 8, bottom: 8, width: 44, height: 44, overflow: 'hidden' }}><Identifier value={`sha256:${'a'.repeat(64)}`} label="Bottom edge digest" /></div>
  </>,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.hover(canvas.getByRole('button', { name: 'Copy Top edge ID' }));
    await waitFor(() => expect(tooltip()).toHaveAttribute('data-side', 'below'));
    await expect(tooltip().parentElement).toBe(document.body);
    await expect(tooltip().getBoundingClientRect().bottom).toBeGreaterThan(canvas.getByTestId('top-container').getBoundingClientRect().bottom);
    await userEvent.hover(tooltip());
    await new Promise(resolve => setTimeout(resolve, 180));
    await expect(tooltip()).toBeVisible();
    await userEvent.unhover(tooltip());
    await waitFor(() => expect(within(document.body).queryByRole('tooltip')).not.toBeInTheDocument());
    await userEvent.hover(canvas.getByRole('button', { name: 'Copy Bottom edge digest' }));
    await waitFor(() => expect(tooltip()).toHaveAttribute('data-side', 'above'));
    const box = tooltip().getBoundingClientRect();
    await expect(box.left).toBeGreaterThanOrEqual(7);
    await expect(box.top).toBeGreaterThanOrEqual(7);
    await expect(box.right).toBeLessThanOrEqual(window.innerWidth - 7);
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight - 7);
    await expect(document.documentElement.scrollWidth).toBeLessThanOrEqual(document.documentElement.clientWidth);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const EmptyAndNumericValues: Story = {
  name: 'Empty values disappear and numeric zero keeps its identity',
  render: () => <><Identifier value="" label="Empty ID" /><Identifier value={null} label="Missing ID" /><Identifier value={0} label="Numeric ID" /></>,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole('button')).toHaveLength(1);
    await userEvent.hover(canvas.getByRole('button', { name: 'Copy Numeric ID' }));
    await expect(within(await within(document.body).findByRole('tooltip')).getByText('0', { selector: 'code' })).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Copy Numeric ID' }));
    await expect(write).toHaveBeenCalledWith('0');
    canvasElement.dataset.demoVerified = 'passed';
  },
};

function ModalIdentifier() {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { dialog.current?.showModal(); }, []);
  return <dialog ref={dialog} aria-label="Identifier modal" style={{ width: 300, height: 120, overflow: 'hidden' }}>
    <button autoFocus type="button" onClick={() => dialog.current?.close()}>Close modal</button>
    <div style={{ height: 32, overflow: 'hidden' }}><Identifier value={value} label="Modal resource ID" /></div>
  </dialog>;
}
export const NativeModal: Story = {
  name: 'Exact ID remains visible and copyable inside a native modal',
  render: () => <ModalIdentifier />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement), dialog = await canvas.findByRole('dialog', { name: 'Identifier modal' });
    await userEvent.hover(canvas.getByRole('button', { name: 'Copy Modal resource ID' }));
    await expect(within(await within(document.body).findByRole('tooltip')).getByText(value)).toBeVisible();
    await expect(tooltip().closest('dialog')).toBe(dialog);
    await expect(tooltip().matches(':popover-open')).toBe(true);
    const box = tooltip().getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    await expect(hit === tooltip() || tooltip().contains(hit)).toBe(true);
    await userEvent.click(canvas.getByRole('button', { name: 'Copy Modal resource ID' }));
    await expect(write).toHaveBeenCalledWith(value);
    await expect(canvas.getByRole('status')).toHaveTextContent('Modal resource ID copied.');
    await userEvent.keyboard('{Escape}');
    await waitFor(() => expect(within(document.body).queryByRole('tooltip')).not.toBeInTheDocument());
    await expect(dialog).toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'Close modal' }));
    canvasElement.dataset.demoVerified = 'passed';
  },
};
