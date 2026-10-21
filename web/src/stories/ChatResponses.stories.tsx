import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within, waitFor, fn } from 'storybook/test';
import { ChatResponseContent } from '../components/MarkdownResponse';
import '../style.css';
import '../pages/model-workspace.css';
import './data-inspector-stories.css';

const python = 'def train_model():\n    print("ready")\n\ntrain_model()';
const json = '{"steps": 73, "recipe": "full_sft"}';
const response = `## Training example

Use **published data** and inspect the \`validation_loss\` before releasing your model.

1. Prepare the dataset.
2. Train and compare the result.

> Keep validation examples separate from training.

\`\`\`python
${python}
\`\`\`

### Configuration

\`\`\`json
${json}
\`\`\`

| Plan | Updates | Validation |
| --- | ---: | --- |
| Quick check | 3 | Check setup |
| Fine-tuning | 73 | Inspect held-out answers |

Read the [dataset guide](https://example.test/datasets).
`;

const meta = {
  title: 'ModelAnvil/Components/Chat responses',
  component: ChatResponseContent,
  args: { text: response },
  parameters: { layout: 'fullscreen' },
  beforeEach({ parameters }) {
    document.documentElement.dataset.theme = parameters.demoTheme ?? 'light';
    delete document.getElementById('storybook-root')?.dataset.demoVerified;
  },
  decorators: [(Story) => <div className="data-story-canvas"><article className="chat-message chat-assistant"><strong>Assistant</strong><Story /></article></div>],
} satisfies Meta<typeof ChatResponseContent>;
export default meta;
type Story = StoryObj<typeof meta>;

async function mockClipboard(run: (write: ReturnType<typeof fn<(text: string) => Promise<void>>>) => Promise<void>) {
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
  const write = fn(async (_text: string) => {});
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: write } });
  try { await run(write); }
  finally {
    if (original) Object.defineProperty(navigator, 'clipboard', original);
    else Reflect.deleteProperty(navigator, 'clipboard');
  }
}

export const MarkdownAndCode: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('heading', { name: 'Training example' })).toBeVisible();
    await expect(canvas.getByRole('table')).toBeVisible();
    await expect(canvas.getByRole('link', { name: 'dataset guide' })).toHaveAttribute('rel', 'noopener noreferrer');
    await mockClipboard(async write => {
      const buttons = canvas.getAllByRole('button', { name: 'Copy code' });
      await userEvent.click(buttons[0]); await waitFor(() => expect(write).toHaveBeenLastCalledWith(python));
      await expect(canvas.getByText('Code copied.')).toBeVisible();
      await userEvent.click(buttons[1]); await waitFor(() => expect(write).toHaveBeenLastCalledWith(json));
      await userEvent.click(canvas.getByRole('button', { name: 'Copy response' }));
      await waitFor(() => expect(write).toHaveBeenLastCalledWith(response));
      await expect(canvas.getByText('Response copied.')).toBeVisible();
    });
    canvasElement.dataset.demoVerified = 'passed';
  },
};

const partial = 'Here is the code:\n\n```javascript\nexport function answer() {\n  return';
const complete = partial + ' 42;\n}\n```\n\n**Done.**';
function StreamingExample() {
  const [text, setText] = useState(partial);
  return <><ChatResponseContent text={text} /><button type="button" onClick={() => setText(complete)}>Complete response</button></>;
}
export const StreamingCode: Story = {
  render: () => <StreamingExample />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await mockClipboard(async write => {
      await userEvent.click(canvas.getByRole('button', { name: 'Copy code' }));
      await waitFor(() => expect(write).toHaveBeenLastCalledWith('export function answer() {\n  return'));
      await userEvent.click(canvas.getByRole('button', { name: 'Complete response' }));
      await expect(canvas.getByText('Done.')).toBeVisible();
      await expect(canvas.queryByText('Code copied.')).not.toBeInTheDocument();
      await userEvent.click(canvas.getByRole('button', { name: 'Copy code' }));
      await waitFor(() => expect(write).toHaveBeenLastCalledWith('export function answer() {\n  return 42;\n}'));
    });
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ClipboardFailure: Story = {
  args: { text: 'A response you can select and copy manually.' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await mockClipboard(async write => {
      write.mockRejectedValueOnce(new Error('Clipboard denied'));
      const copy = canvas.getByRole('button', { name: 'Copy response' });
      await userEvent.click(copy);
      await expect(canvas.findByText('Copy unavailable. Select the text to copy it.')).resolves.toBeVisible();
      await expect(copy).toBeEnabled(); await userEvent.click(copy);
      await expect(canvas.findByText('Response copied.')).resolves.toBeVisible();
    });
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const LongCode: Story = { args: { text: '```text\n' + 'unbroken_code_identifier_'.repeat(30) + '\n```' } };
export const StructuredJson: Story = { args: { text: '{"answer":"Use independent validation examples.","passed":false,"score":0}' } };
export const Dark: Story = { ...MarkdownAndCode, parameters: { demoTheme: 'dark' } };
export const Preview: Story = {};
