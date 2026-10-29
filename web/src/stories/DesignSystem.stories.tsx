import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { ArrowRight, ArrowUpRight } from 'lucide-react';
import '../main';
import {
  Badge, Button, Card, Checkbox, Dialog, Disclosure, Field, FileInput, KeyValueList, MetricSummary, MultilineField, Notice, PageHeader,
  RecordTable, Section, SegmentedControl, Select, Stat, StatRow, StatusBadge, Tab, TabList, Toolbar,
} from '../components/ui';
import { JourneySteps } from '../components/primitives/Journey';
import { FINE_TUNE_STAGES } from '../api/journey';
import { ThemeControl } from '../components/ThemeControl';
import { EmptyState, Feedback } from '../components/Feedback';

function Components() {
  const [saved, setSaved] = useState(0);
  const [tab, setTab] = useState('configure');
  const [mode, setMode] = useState<'guided' | 'advanced'>('guided');
  const [dialog, setDialog] = useState(false);
  return <main id="workspace-content" className="page-content" style={{ maxWidth: 960 }}>
    <PageHeader title="FigCraft components" description="Shared variants and native form behavior." actions={<div className="actions"><ThemeControl /></div>} />
    <Section title="Actions and fields" description="Buttons, fields and the labelled controls pages compose.">
      <form onSubmit={event => { event.preventDefault(); setSaved(value => value + 1); }} style={{ display: 'grid', gap: 'var(--space-16)' }}>
        <label>Project label<Field name="project" defaultValue="Research workspace" required /></label>
        <label>Notes<MultilineField defaultValue="Reusable configuration" rows={2} /></label>
        <Select label="Training plan" hint="Recommended plans scale with your examples." defaultValue="recommended" options={[{ value: 'recommended', label: 'Recommended' }, { value: 'quick', label: 'Quick check' }, { value: 'custom', label: 'Custom' }]} />
        <Checkbox label="Detect duplicate examples" hint="Exact duplicates are dropped before training." defaultChecked />
        <FileInput label="Training file" hint="JSONL, JSON or CSV · up to 16 MiB." />
        <SegmentedControl label="Configuration mode" value={mode} onChange={value => setMode(value as typeof mode)} options={[{ value: 'guided', label: 'Guided' }, { value: 'advanced', label: 'Advanced' }]} />
        <div className="actions"><Button variant="primary">Save configuration <ArrowRight size={16} aria-hidden="true" /></Button><Button type="button">Secondary</Button><Button type="button" variant="quiet">Quiet</Button><Button disabled>Unavailable</Button><Button type="button" onClick={() => setDialog(true)}>Open dialog</Button></div>
        <output aria-live="polite">Saved {saved} times</output>
      </form>
    </Section>
    <Section title="Tabs, status and feedback">
      <TabList label="Example view">{['configure', 'history'].map(value => <Tab key={value} id={`example-tab-${value}`} aria-controls="example-panel" aria-selected={tab === value} onClick={() => setTab(value)}>{value}</Tab>)}</TabList>
      <div id="example-panel" role="tabpanel" aria-labelledby={`example-tab-${tab}`}><p>{tab === 'configure' ? 'Saved configuration' : 'Recorded runs'}</p></div>
      <div className="actions"><Badge>Neutral</Badge><Badge tone="success">Ready</Badge><Badge tone="caution">Pending</Badge><Badge tone="error">Failed</Badge></div>
      <div className="actions">{['queued', 'running', 'succeeded', 'interrupted', 'failed', 'accepted_without_edit', ''].map(status => <StatusBadge key={status} status={status} />)}</div>
      <Notice tone="info">Information uses the primary accent.</Notice><Notice tone="success">Configuration saved.</Notice><Notice tone="caution">Review the recorded evidence.</Notice><Notice tone="error">A retry is available.</Notice>
      <Feedback state="loading" title="Loading workspace data…" />
      <EmptyState title="No training runs yet" description="Start a run to see progress here." action={<Button type="button">Start training</Button>} layout="centered" />
    </Section>
    <Section title="Structure" description="Stats, facts, journeys and disclosures.">
      <StatRow><Stat label="Elapsed" value="4 min" /><Stat label="Training loss" value="1.887" hint="step 50" /><Stat label="Validation loss" value="Not reported" /><Stat label="Checkpoints" value={6} tone="success" /></StatRow>
      <KeyValueList items={[{ label: 'Base model', value: 'SmolLM2-135M Instruct' }, { label: 'Dataset', value: 'Support tickets · 120 examples' }, { label: 'Compute', value: 'This computer' }]} />
      <JourneySteps steps={FINE_TUNE_STAGES} current={1} label="Fine-tuning journey" />
      <Toolbar label="Filters" actions={<Button type="button" variant="primary">Create job</Button>}><Field aria-label="Search jobs" placeholder="Search jobs" /><Select aria-label="Status" defaultValue="all" options={[{ value: 'all', label: 'All states' }, { value: 'running', label: 'Running' }]} /></Toolbar>
      <Disclosure summary="Advanced settings"><p>Learning rate, seed and validation interval live here.</p></Disclosure>
      <Disclosure summary="Details" variant="card"><KeyValueList items={[{ label: 'Run ID', value: '30000000-0000-4000-8000-000000000001' }]} /></Disclosure>
    </Section>
    <Card tone="accent" padded><h2>Responsive records</h2><RecordTable>
      <caption>One record with the same action on every screen size.</caption>
      <thead><tr><th>Run</th><th>State</th><th>Action</th></tr></thead>
      <tbody><tr><td>Example run</td><td><Badge tone="success">Completed</Badge></td><td><Button type="button" onClick={() => setSaved(value => value + 1)}>Inspect record</Button></td></tr></tbody>
    </RecordTable></Card>
    <Dialog title="Register tokenizer" description="Dialogs render in place and close on Escape." open={dialog} onClose={() => setDialog(false)} footer={<><Button type="button" onClick={() => setDialog(false)}>Cancel</Button><Button type="button" variant="primary" onClick={() => setDialog(false)}>Register</Button></>}>
      <label>Tokenizer name<Field defaultValue="smollm2-tokenizer" /></label>
    </Dialog>
  </main>;
}

const meta = {
  title: 'ModelAnvil/Components/FigCraft', component: Components,
  beforeEach({ parameters }) { localStorage.setItem('modelanvil_theme', parameters.demoTheme ?? 'light'); },
} satisfies Meta<typeof Components>;
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
    await userEvent.click(canvas.getByRole('button', { name: 'Advanced' }));
    await expect(canvas.getByRole('button', { name: 'Advanced' })).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(canvas.getByRole('button', { name: 'Open dialog' }));
    await expect(canvas.getByRole('dialog', { name: 'Register tokenizer' })).toBeVisible();
    await userEvent.keyboard('{Escape}');
    await expect(canvas.queryByRole('dialog', { name: 'Register tokenizer' })).not.toBeInTheDocument();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const Dark: Story = { ...Variants, parameters: { demoTheme: 'dark' } };

function InteractionExamples() {
  const [name, setName] = useState('');
  const invalid = name.trim().length < 3;
  return <main id="workspace-content" className="page-content" style={{ maxWidth: 700 }}>
    <PageHeader title="Interactive component states" actions={<div className="actions"><ThemeControl /></div>} />
    <Card padded><div style={{ display: 'grid', gap: 'var(--space-16)' }}>
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
  return <main id="workspace-content" className="page-content" style={{ maxWidth: 800 }}>
    <PageHeader title="Loading and recovery" actions={<div className="actions"><ThemeControl /></div>} />
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
  return <main id="workspace-content" className="page-content" style={{ maxWidth: 960 }}>
    <PageHeader title="Resource summaries" description="Demo values demonstrate actions, read-only metrics, and long content." actions={<div className="actions"><ThemeControl /></div>} />
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
