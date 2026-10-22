import type { StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import screens from './Screens.stories';
import { demoRequests } from './demo-network';

const meta = { ...screens, title: 'ModelAnvil/Actions/Input forms' };
export default meta;
type Story = StoryObj<typeof meta>;
const submitted = (path: string) => [...demoRequests].reverse().find(request => request.path === path && request.method === 'POST')?.body;
async function readyWorkspace(canvasElement: HTMLElement) {
  const canvas = within(canvasElement);
  await expect(canvas.findByText('Assistant Research · Demo', { selector: 'option' })).resolves.toBeInTheDocument();
  await waitFor(() => expect(canvas.queryByText('Loading project scope…')).not.toBeInTheDocument());
}
async function readySelect(select: HTMLElement, index = 1) {
  await waitFor(() => expect(within(select).getAllByRole('option').length).toBeGreaterThan(index));
  await userEvent.selectOptions(select, (within(select).getAllByRole('option')[index] as HTMLOptionElement).value);
}

export const EvaluationSuite: Story = {
  parameters: { demoRoute: '#evaluation', demoHeading: 'Evaluation', demoApiPath: '/api/v1/evaluation-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await readyWorkspace(canvasElement);
    const register = await canvas.findByRole('button', { name: 'Register evaluation suite' });
    await waitFor(() => expect(register).toBeEnabled());
    await userEvent.click(register);
    await userEvent.type(await canvas.findByLabelText('Suite name'), 'Form-built checks');
    const row = within(canvas.getByRole('group', { name: 'Case 1' }));
    await userEvent.clear(row.getByLabelText('Input prompt'));
    await userEvent.type(row.getByLabelText('Input prompt'), 'Exact prompt\n');
    await userEvent.clear(row.getByLabelText('Expected response'));
    await userEvent.type(row.getByLabelText('Expected response'), ' exact answer ');
    await userEvent.click(canvas.getByRole('button', { name: 'Pin evaluation suite' }));
    await expect(canvas.findByText('Evaluation suite pinned. Select a candidate to create an evaluation.')).resolves.toBeVisible();
    await expect(submitted('/api/v1/evaluation-suites/register-cpu/')).toMatchObject({ name: 'Form-built checks', cases: [{ case_id: 'case-1', input_prompt: 'Exact prompt\n', expected_output: ' exact answer ', slice: 'general' }] });
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ContextOverrides: Story = {
  parameters: { demoRoute: '#context-lab', demoHeading: 'Prompt compiler', demoApiPath: '/api/v1/context-recipe-versions/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await readyWorkspace(canvasElement);
    await readySelect(await canvas.findByLabelText('Recipe version'));
    await userEvent.click(canvas.getByRole('checkbox', { name: 'Override Question' }));
    const question = canvas.getByLabelText('Question override');
    await userEvent.clear(question);
    await userEvent.type(question, 'What is the source?\n');
    await userEvent.click(canvas.getByRole('button', { name: 'Compile Context Recipe' }));
    await expect(canvas.findByLabelText('Exact compiled prompt')).resolves.toHaveTextContent('What is the source?');
    await expect([...demoRequests].reverse().find(request => request.method === 'POST' && request.path.endsWith('/compile/'))?.body).toEqual({ variables: { question: 'What is the source?\n' } });
    await userEvent.click(canvas.getByRole('button', { name: 'Overview' }));
    await userEvent.click(canvas.getByRole('button', { name: 'Context' }));
    await userEvent.click(canvas.getByRole('tab', { name: 'Compile' }));
    await expect(canvas.findByLabelText('Question override')).resolves.toHaveValue('What is the source?\n');
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const WorkflowInputs: Story = {
  parameters: { demoRoute: '#workflows', demoHeading: 'Workflows', demoApiPath: '/api/v1/jobs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await readyWorkspace(canvasElement);
    const create = await canvas.findByRole('button', { name: 'Create job' });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);
    await userEvent.type(canvas.getByLabelText('Job name'), 'Form-built job');
    await readySelect(canvas.getByLabelText('Worker pool'));
    await readySelect(canvas.getByLabelText('Budget policy'));
    await userEvent.type(canvas.getByLabelText('Estimated usage'), '1');
    const fields = within(canvas.getByRole('group', { name: 'Job inputs' }));
    await userEvent.click(fields.getByRole('button', { name: 'Add field' }));
    await userEvent.type(fields.getByLabelText('Field name'), 'attempts');
    await userEvent.selectOptions(fields.getByLabelText('Value type'), 'number');
    await userEvent.type(fields.getByLabelText('Value'), '0');
    await userEvent.click(canvas.getByRole('button', { name: 'Queue job' }));
    await expect(canvas.findByText('Job “Form-built job” created. Current state: queued.')).resolves.toBeVisible();
    await expect(submitted('/api/v1/jobs/')?.payload).toEqual({ attempts: 0 });
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const TokenizerSymbols: Story = {
  parameters: { demoRoute: '#training', demoHeading: 'Training', demoApiPath: '/api/v1/training-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await readyWorkspace(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Tokenizer' }));
    const dialog = within(canvas.getByRole('dialog', { name: 'Register Tokenizer' }));
    await userEvent.click(dialog.getByRole('button', { name: 'Mistral' }));
    await expect(dialog.getAllByLabelText('Token symbol')[0]).toHaveValue('<s>');
    await userEvent.click(dialog.getByRole('button', { name: 'Register Tokenizer' }));
    await waitFor(() => expect(submitted('/api/v1/tokenizers/')).toMatchObject({ name: 'Mistral-Tokenizer', special_tokens: { bos_token: '<s>', eos_token: '</s>' } }));
    await expect(canvas.queryByRole('dialog')).not.toBeInTheDocument();
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const AlignmentSettings: Story = {
  parameters: { demoRoute: '#alignment', demoHeading: 'Alignment', demoApiPath: '/api/v1/alignment-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await readyWorkspace(canvasElement);
    const create = await canvas.findByRole('button', { name: 'New alignment plan' });
    await waitFor(() => expect(create).toBeEnabled());
    await userEvent.click(create);
    await userEvent.selectOptions(canvas.getByLabelText('Algorithm'), 'verifier_rl');
    await readySelect(canvas.getByLabelText('Policy model version'));
    await readySelect(canvas.getByLabelText('Training preference artifact'));
    await readySelect(canvas.getByLabelText('Held-out preference artifact'), 2);
    await userEvent.clear(canvas.getByLabelText('Learning rate'));
    await userEvent.type(canvas.getByLabelText('Learning rate'), '0.01');
    await userEvent.selectOptions(canvas.getByLabelText('Verification method'), 'numeric_tolerance');
    await userEvent.type(canvas.getByLabelText('Numeric tolerance'), '0');
    await userEvent.click(canvas.getByRole('button', { name: 'Create alignment configuration' }));
    await expect(canvas.findByText('Alignment plan saved with verified preference bytes. Execute when ready.')).resolves.toBeVisible();
    await expect(submitted('/api/v1/alignment-runs/')).toMatchObject({ algorithm: 'verifier_rl', hyperparameters: { learning_rate: 0.01 }, verifier_spec: { type: 'numeric_tolerance', tolerance: 0 } });
    await expect(demoRequests.filter(request => request.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};
