import type { StoryObj } from '@storybook/react-vite';
import { expect, within, userEvent, waitFor } from 'storybook/test';
import screenMeta from './Screens.stories';
import { demoRequests } from './demo-network';

const meta = { ...screenMeta, title: 'ModelAnvil/Actions/ML' };
export default meta;
type Story = StoryObj<typeof meta>;

export const InitializeCpuBase: Story = {
  name: 'Initialize CPU base',
  parameters: { demoRoute: '#models', demoHeading: 'Models', demoApiPath: '/api/v1/models/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole('button', { name: 'Initialize CPU base' }));
    await userEvent.type(canvas.getByLabelText('CPU base model name'), 'Storybook CPU base');
    await userEvent.click(canvas.getByRole('button', { name: 'Create pinned CPU base' }));
    await expect(canvas.findByText('Demo CPU base “Storybook CPU base” registered in this Storybook session.')).resolves.toBeVisible();
    await expect(canvas.findByRole('heading', { name: 'Storybook CPU base' })).resolves.toBeVisible();
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ExecuteEvaluation: Story = {
  name: 'Execute evaluation',
  parameters: { demoRoute: '#evaluation', demoHeading: 'Evaluation', demoApiPath: '/api/v1/evaluation-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const selector = await canvas.findByLabelText('Evaluation run to visualize');
    await waitFor(() => expect(within(selector).getAllByRole('option').length).toBeGreaterThan(1));
    await userEvent.selectOptions(selector, '30000000-0000-4000-8000-000000000007');
    await userEvent.clear(canvas.getByLabelText('Maximum generated tokens'));
    await userEvent.type(canvas.getByLabelText('Maximum generated tokens'), '4');
    await userEvent.click(canvas.getByRole('button', { name: 'Execute CPU evaluation' }));
    await expect(canvas.findByText('Demo evaluation completed with fictional Storybook results.')).resolves.toBeVisible();
    await expect(canvas.findByText('SUPPORT-001', { exact: true })).resolves.toBeVisible();
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const RegisterEvaluationSuite: Story = {
  name: 'Register evaluation suite',
  parameters: { demoRoute: '#evaluation', demoHeading: 'Evaluation', demoApiPath: '/api/v1/evaluation-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const register = await canvas.findByRole('button', { name: 'Register evaluation suite' });
    await waitFor(() => expect(register).toBeEnabled());
    await userEvent.click(register);
    await userEvent.type(canvas.getByLabelText('Suite name'), 'Storybook checks');
    await userEvent.type(canvas.getByLabelText(/Source group ID/), 'storybook-held-out');
    await userEvent.click(canvas.getByRole('button', { name: 'Pin evaluation suite' }));
    await expect(canvas.findByText('Suite r1 pinned as protected evaluation with 1 source group.')).resolves.toBeVisible();
    await expect(canvas.getByLabelText('Evaluation suite version')).toHaveValue('3');
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const ExecuteAlignment: Story = {
  name: 'Execute CPU alignment',
  parameters: { demoRoute: '#alignment', demoHeading: 'Alignment', demoApiPath: '/api/v1/alignment-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const selector = await canvas.findByLabelText('Alignment run to visualize');
    await waitFor(() => expect(within(selector).getAllByRole('option').length).toBeGreaterThan(1));
    await userEvent.selectOptions(selector, '30000000-0000-4000-8000-000000000010');
    await userEvent.click(canvas.getByRole('button', { name: 'Execute CPU alignment' }));
    await expect(canvas.findByText('Demo alignment completed with fictional Storybook results.')).resolves.toBeVisible();
    await expect(canvas.findByRole('heading', { name: 'Recorded optimizer history' })).resolves.toBeVisible();
    await expect(canvas.getByText(/Candidate: Anvil Assistant/)).toBeVisible();
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const CancelAlignment: Story = {
  name: 'Cancel alignment',
  parameters: { demoRoute: '#alignment', demoHeading: 'Alignment', demoApiPath: '/api/v1/alignment-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const selector = await canvas.findByLabelText('Alignment run to visualize');
    await waitFor(() => expect(within(selector).getAllByRole('option').length).toBeGreaterThan(1));
    await userEvent.selectOptions(selector, '30000000-0000-4000-8000-000000000008');
    await userEvent.click(canvas.getByRole('button', { name: 'Cancel alignment' }));
    await expect(canvas.findByText('Demo alignment cancelled with fictional Storybook results.')).resolves.toBeVisible();
    await expect(canvas.getByRole('progressbar', { name: 'Alignment committed steps' })).toHaveAttribute('value', '30');
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const RegisterPreferencePairs: Story = {
  name: 'Register preference pairs',
  parameters: { demoRoute: '#alignment', demoHeading: 'Alignment', demoApiPath: '/api/v1/alignment-runs/' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const registration = await canvas.findByRole('button', { name: 'Register preference pairs' });
    await waitFor(() => expect(registration).toBeEnabled());
    await userEvent.click(registration);
    await userEvent.type(canvas.getByLabelText('Preference artifact name'), 'Storybook preferences');
    await userEvent.click(canvas.getByRole('button', { name: 'Add preference pair' }));
    const pair = within(canvas.getByRole('group', { name: 'Preference pair 1' }));
    await userEvent.type(pair.getByLabelText('Prompt'), 'Say a');
    await userEvent.type(pair.getByLabelText('Preferred response'), 'a');
    await userEvent.type(pair.getByLabelText('Rejected response'), 'b');
    await userEvent.click(canvas.getByRole('button', { name: 'Commit preference artifact' }));
    await expect(canvas.findByText('Preference artifact “Storybook preferences” committed. Select separate training and held-out inputs.')).resolves.toBeVisible();
    await userEvent.click(canvas.getByRole('button', { name: 'New alignment plan' }));
    await expect(within(canvas.getByLabelText('Training preference artifact')).getByRole('option', { name: /Storybook preferences/ })).toBeInTheDocument();
    await expect(demoRequests.filter(r => r.status >= 400)).toHaveLength(0);
    canvasElement.dataset.demoVerified = 'passed';
  },
};
