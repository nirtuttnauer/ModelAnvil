import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { ArrowRight, ArrowUpRight } from 'lucide-react';
import '../main';
import { Badge, Button, Card, Field, MetricSummary, MultilineField, Notice, RecordTable, Tab } from '../components/ui';
import { ThemeControl } from '../components/ThemeControl';
import { Feedback } from '../components/Feedback';

function Components() {
  const [saved, setSaved] = useState(0);
  const [tab, setTab] = useState('configure');
  return <main id="workspace-content" style={{ display: 'grid', gap: 'var(--space-20)', maxWidth: 960, margin: 'auto' }}>
    <header><h1>FigCraft components</h1><p>Shared variants and native form behavior.</p><div className="actions"><ThemeControl /></div></header>
    <Card tone="surface"><div className="panel-body">
      <h2>Actions and fields</h2>
      <form onSubmit={event => { event.preventDefault(); setSaved(value => value + 1); }} style={{ display: 'grid', gap: 'var(--space-16)' }}>
        <label>Project label<Field name="project" defaultValue="Research workspace" required /></label>
        <label>Notes<MultilineField defaultValue="Reusable configuration" /></label>
        <div className="actions"><Button variant="primary">Save configuration <ArrowRight size={16} aria-hidden="true" /></Button><Button type="button">Secondary</Button><Button type="button" variant="quiet">Quiet</Button><Button disabled>Unavailable</Button></div>
        <output aria-live="polite">Saved {saved} times</output>
      </form>
    </div></Card>
    <Card tone="subtle"><div className="panel-body"><h2>Tabs and feedback</h2>
      <div className="training-tabs" role="tablist" aria-label="Example view">{['configure', 'history'].map(value => <Tab key={value} id={`example-tab-${value}`} aria-controls="example-panel" aria-selected={tab === value} onClick={() => setTab(value)}>{value}</Tab>)}</div>
      <div id="example-panel" role="tabpanel" aria-labelledby={`example-tab-${tab}`}><p>{tab === 'configure' ? 'Saved configuration' : 'Recorded runs'}</p></div>
      <div className="actions"><Badge>Neutral</Badge><Badge tone="success">Ready</Badge><Badge tone="caution">Pending</Badge><Badge tone="error">Failed</Badge></div>
      <Notice tone="success">Configuration saved.</Notice><Notice tone="caution">Review the recorded evidence.</Notice><Notice tone="error">A retry is available.</Notice>
    </div></Card>
    <Card tone="accent"><div className="panel-body"><h2>Responsive records</h2><RecordTable>
      <caption>One record with the same action on every screen size.</caption>
      <thead><tr><th>Run</th><th>State</th><th>Action</th></tr></thead>
      <tbody><tr><td>Example run</td><td><Badge tone="success">Completed</Badge></td><td><Button type="button" onClick={() => setSaved(value => value + 1)}>Inspect record</Button></td></tr></tbody>
    </RecordTable></div></Card>
  </main>;
}

const meta = { title: 'ModelAnvil/Components/FigCraft', component: Components } satisfies Meta<typeof Components>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Variants: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.clear(canvas.getByLabelText('Project label'));
    await userEvent.type(canvas.getByLabelText('Project label'), 'Updated project');
    await userEvent.click(canvas.getByRole('button', { name: 'Save configuration' }));
    await expect(canvas.getByText('Saved 1 times')).toBeVisible();
    await expect(canvas.getByRole('button', { name: 'Unavailable' })).toBeDisabled();
    await userEvent.click(canvas.getByRole('button', { name: 'Inspect record' }));
    await expect(canvas.getByText('Saved 2 times')).toBeVisible();
    await expect(canvas.getByLabelText('Project label')).toHaveValue('Updated project');
    await userEvent.click(canvas.getByRole('tab', { name: 'history' }));
    await expect(canvas.getByRole('tabpanel')).toHaveTextContent('Recorded runs');
    canvasElement.dataset.demoVerified = 'passed';
  },
};

function InteractionExamples() {
  const [name, setName] = useState('');
  const invalid = name.trim().length < 3;
  return <main id="workspace-content" style={{ maxWidth: 700, margin: 'auto' }}>
    <h1>Interactive component states</h1><ThemeControl />
    <Card><div className="panel-body" style={{ display: 'grid', gap: 'var(--space-16)' }}>
      <h2>Pointer and keyboard feedback</h2>
      <div className="actions"><Button type="button" variant="primary">Primary action</Button><Button type="button">Secondary action</Button><Button type="button" variant="quiet">Quiet action</Button><Button disabled>Disabled action</Button></div>
      <label>Workspace name<Field value={name} onChange={event => setName(event.target.value)} aria-invalid={invalid} aria-describedby={invalid ? 'interaction-name-error' : undefined} /></label>
      {invalid && <p id="interaction-name-error" className="error-text">Use at least three characters.</p>}
      <label>Disabled field<Field disabled value="Read-only example" /></label>
      <label>Review notes<MultilineField aria-invalid="true" aria-describedby="interaction-notes-error" defaultValue="" rows={3} /></label>
      <p id="interaction-notes-error" className="error-text">Add a review note before continuing.</p>
    </div></Card>
  </main>;
}

export const InteractionStates: Story = {
  render: () => <InteractionExamples />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const field = canvas.getByLabelText('Workspace name');
    await userEvent.click(field);
    await expect(field).toHaveFocus();
    await expect(field).toHaveAttribute('aria-invalid', 'true');
    await userEvent.type(field, 'Research');
    await expect(field).toHaveAttribute('aria-invalid', 'false');
    await expect(canvas.queryByText('Use at least three characters.')).not.toBeInTheDocument();
    await expect(canvas.getByLabelText('Disabled field')).toBeDisabled();
    await expect(canvas.getByRole('button', { name: 'Disabled action' })).toBeDisabled();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

function FeedbackExamples() {
  const [failed, setFailed] = useState(true);
  const [submits, setSubmits] = useState(0);
  return <main id="workspace-content" style={{ maxWidth: 800, margin: 'auto' }}>
    <h1>Loading and recovery</h1><ThemeControl />
    <Feedback state="loading" title="Loading workspace data…" description="Waiting for workspace data." />
    <Feedback state="empty" title="No matching sources" description="Try another search or clear your filters." />
    <form aria-label="Recovery example" onSubmit={event => { event.preventDefault(); setSubmits(value => value + 1); }}>
      {failed ? <Feedback state="error" title="The catalog could not load." description="Check your connection and try again."
        action={<Button type="button" onClick={() => setFailed(false)}>Try again</Button>} /> : <p role="status">Catalog reloaded.</p>}
      <output>Form submissions: {submits}</output>
    </form>
  </main>;
}

export const FeedbackStates: Story = {
  render: () => <FeedbackExamples />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole('alert')).toBeVisible();
    await expect(canvas.getByText('No matching sources')).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

export const LoadingAndRecovery: Story = {
  render: () => <FeedbackExamples />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText('Loading workspace data…')).toBeVisible();
    await expect(canvas.getByRole('alert')).toHaveTextContent('The catalog could not load.');
    await userEvent.click(canvas.getByRole('button', { name: 'Try again' }));
    await expect(canvas.queryByRole('alert')).not.toBeInTheDocument();
    await expect(canvas.getByText('Catalog reloaded.')).toBeVisible();
    await expect(canvas.getByText('Form submissions: 0')).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};

function MetricExamples() {
  const [inspected, setInspected] = useState(0);
  const [submits, setSubmits] = useState(0);
  return <main id="workspace-content" style={{ maxWidth: 960, margin: 'auto' }}>
    <h1>Resource summaries</h1><div className="actions"><ThemeControl /></div>
    <p>Demo values demonstrate actions, read-only metrics, and long content.</p>
    <form aria-label="Metric actions" onSubmit={event => { event.preventDefault(); setSubmits(value => value + 1); }}>
      <div className="cards">
        <MetricSummary label="Datasets" value="2" detail={<>Total resources <ArrowUpRight size={12} aria-hidden="true" /></>} onClick={() => setInspected(value => value + 1)} />
        <MetricSummary as="article" label="Active reservations" value={0} detail="Awaiting completion or release" />
        <MetricSummary as="article" label="Resource units with recorded usage" value="12345678901234567890" detail="Each resource unit kept separate" />
        <MetricSummary label="Unavailable resource count" value="—" detail="Waiting for workspace data" disabled />
        <MetricSummary as="article" label="Budget policies" value={4} />
      </div>
      <output aria-live="polite">Inspected {inspected} times · Form submissions: {submits}</output>
    </form>
  </main>;
}

export const ResourceSummaries: Story = {
  render: () => <MetricExamples />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const action = canvas.getByRole('button', { name: 'Datasets 2 Total resources' });
    await action.focus();
    await userEvent.keyboard('{Enter}');
    await expect(canvas.getByText('Inspected 1 times · Form submissions: 0')).toBeVisible();
    await expect(canvas.getByRole('button', { name: /Unavailable resource count/ })).toBeDisabled();
    await expect(canvas.getAllByRole('article')).toHaveLength(3);
    canvasElement.dataset.demoVerified = 'passed';
  },
};
