import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, waitFor, within } from 'storybook/test';
import { PreflightChecklist, type PreflightReport } from '../components/PreflightChecklist';
import { ResourcePicker, type ResourceOption } from '../components/ResourcePicker';
import { MetricComparison } from '../components/MetricComparison';
import { ReleaseGateChecklist } from '../components/ReleaseGateChecklist';
import { LineagePanel, type LineagePath } from '../components/LineagePanel';
import { InspectorPanel } from '../components/InspectorPanel';
import { ContextBlockEditor, ContextBlockInputs } from '../components/ContextBlockEditor';
import { RetrievalEvidenceCard } from '../components/RetrievalEvidenceCard';
import { objectInput } from '../components/form-data';
import '../style.css';
import './workbench-stories.css';

const meta = {
  title: 'ModelAnvil/Components/Engineering components', parameters: { layout: 'fullscreen' },
  beforeEach({ parameters }) { document.documentElement.dataset.theme = parameters.demoTheme ?? 'light'; delete document.getElementById('storybook-root')?.dataset.demoVerified; },
  decorators: [(Story, context) => <main className="workbench-story-canvas"><p className="wb-muted">MODELAnvil · SYNTHETIC COMPONENT PREVIEWS</p><h1>Engineering components</h1><h2>{context.name}</h2><Story /></main>],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;
const approved: PreflightReport = {
  status: 'approved', recipe_type: 'full_sft', execution_mode: 'worker', preflight_token: 'synthetic-preview-only', expires_in_seconds: 300,
  checks: [
    { check: 'pinned-inputs', category: 'inputs', status: 'pass', blocking: true, reason: 'Exact dataset and model revisions are pinned.' },
    { check: 'runtime-ready', category: 'compute', status: 'pass', blocking: true, reason: 'Synthetic CPU worker supports the selected profile.', detail: { cpu_slots: 1, memory_bytes: 104857600 } },
    { check: 'budget-capacity', category: 'budget', status: 'pass', blocking: true, reason: 'The configured step allowance covers this request.' },
  ], blocking_checks: [], samples: [{ sample_id: 'sample-1', token_count: 3, text_preview: 'Keep this source text.\n', token_ids: [0, 7, 42] }], sample_count: 20,
  pins: { model_version_id: '10000000-0000-4000-8000-000000000004', dataset_revision_id: '20000000-0000-4000-8000-000000000002' },
  requirements: { runtime: 'CPU character training · synthetic preview', cpu_slots: 1, memory_bytes: 104857600, storage_bytes: 1048576, config: { learning_rate: 0.05 }, optimizer: 'SGD' },
  budget: { requested: 50, unit: 'optimizer_steps', remaining: '250', limit: '300', committed: '50' },
  estimate: { known: false, source: 'No measured pilot in this fixture', assumptions: ['Duration requires a matching measured pilot.'], units: { duration: 'seconds' }, currency: null, uncertainty: 'Unknown', total_tokens: 2000, estimated_cost: { known: false, reason: 'No recorded rate' } },
  capacity_note: 'This Storybook fixture represents no connected runtime.', runtime_scope: { targets: [], available: [], unavailable: [] },
};
const blocked: PreflightReport = { ...approved, status: 'blocked', preflight_token: null, blocking_checks: ['budget-capacity'], checks: [...approved.checks.slice(0, 2), { check: 'budget-capacity', category: 'budget', status: 'fail', blocking: true, reason: '50 steps requested; 0 steps remain.', corrective_action: 'Choose a policy with sufficient remaining steps.', detail: { requested: 50, remaining: 0 } }] };
const resources: ResourceOption[] = [
  { value: '4', id: '10000000-0000-4000-8000-000000000004', name: 'Support assistant', revision: 4, state: 'ready', description: 'Supports the selected CPU evaluation profile.', href: '#resources/model-version/10000000-0000-4000-8000-000000000004' },
  { value: '3', id: '10000000-0000-4000-8000-000000000003', name: 'Support assistant', revision: 3, state: 'ready', description: 'Previous revision.' },
  { value: '2', id: '10000000-0000-4000-8000-000000000002', name: 'Imported model', revision: 2, unavailable: 'This format has no installed CPU evaluation runtime.' },
];
const metrics = [
  { key: 'accuracy', slice_name: 'all', value: 0.92, sample_count: 100, uncertainty_interval: { lower: 0.88, upper: 0.96 } },
  { key: 'accuracy', slice_name: 'empty', value: 0, sample_count: 0, uncertainty_interval: null },
  { key: 'loss', slice_name: 'all', value: 0.1, sample_count: 100, uncertainty_interval: null },
];
const baseline = [
  { key: 'loss', slice_name: 'all', value: 0.2, sample_count: 100, uncertainty_interval: null },
  { key: 'accuracy', slice_name: 'all', value: 0.9, sample_count: 100, uncertainty_interval: { lower: 0.86, upper: 0.94 } },
  { key: 'accuracy', slice_name: 'baseline_only', value: 0.8, sample_count: 20, uncertainty_interval: null },
];
const gates = [
  { key: 'held_out_accuracy', required: 0.9, actual: 0.92, passed: true },
  { key: 'baseline_regression', required: 'No regression', actual: -0.03, passed: false },
  { key: 'license_evidence', required: 'Recorded license authority', actual: null, passed: false },
];
const lineage: LineagePath[] = [{ label: 'Dataset → training → recorded output', nodes: [
  { kind: 'Dataset', name: 'Support corpus', id: 'dataset-r2', revision: 2, href: '#dataset-r2' },
  { kind: 'Training', name: 'Full SFT', id: 'training-1', state: 'completed', href: '#training-1' },
  { kind: 'Model', name: 'Support assistant', id: resources[0].id, revision: 4, href: resources[0].href },
] }, { label: 'Model → evaluation', nodes: [{ kind: 'Model', ...resources[0] }, { kind: 'Evaluation', name: 'Held-out evaluation', id: 'eval-1', state: 'completed', href: '#eval-1' }] }];
const blocks = [
  { key: 'system', label: 'System instruction', content: 'Use only recorded evidence.', role: 'system', essential: true },
  { key: 'evidence', label: 'Evidence template', content: 'Published revisions are immutable.', role: 'system', essential: false },
  { key: 'question', label: 'Question template', content: 'How do I pin a dataset?', role: 'user', essential: true },
];
const chunk = { chunk_id: '60000000-0000-4000-8000-000000000071', score: 0, text: 'Published dataset revisions are immutable.\nValidate dataset splits before launching training. '.repeat(5) + '<script>This is source text, never executable markup.</script>', metadata: { document_title: 'Dataset preparation guide', source_uri: 'https://example.test/dataset-guide', revision: 2 } };
function verified(canvas: HTMLElement) { canvas.dataset.demoVerified = 'passed'; }
function PickerDemo({ initial = '', disabled = false }: { initial?: string; disabled?: boolean }) {
  const [value, setValue] = useState(initial), [saved, setSaved] = useState('');
  return <form aria-label="Resource selection" onSubmit={e => { e.preventDefault(); setSaved(value); }}><ResourcePicker label="Candidate model" required disabled={disabled} value={value} onChange={setValue} options={resources} /><button className="primary" disabled={disabled}>Use selected revision</button>{saved && <p role="status">Selected resource value: {saved}</p>}</form>;
}
function InspectorDemo() {
  const [open, setOpen] = useState(false);
  return <><button onClick={() => setOpen(true)}>Inspect worker</button>{open && <InspectorPanel title="Research worker" eyebrow="Worker registration" onClose={() => setOpen(false)} footer={<a href="#infrastructure">Open Infrastructure</a>}><dl className="wb-facts"><div><dt>Pool</dt><dd>CPU research</dd></div><div><dt>Heartbeat</dt><dd>Not reported</dd></div></dl><p className="wb-muted">Registration alone does not establish runtime readiness.</p></InspectorPanel>}</>;
}
function ContextDemo() {
  const [current, setCurrent] = useState(blocks), [saved, setSaved] = useState(false);
  return <form aria-label="Context editor" onSubmit={e => { e.preventDefault(); setSaved(true); }}><ContextBlockEditor blocks={current} onChange={(key, content) => { setCurrent(current.map(block => block.key === key ? { ...block, content } : block)); setSaved(false); }} /><button className="primary">Save context</button>{saved && <p role="status">Context saved.</p>}</form>;
}
function OverridesDemo({ initial = '{}' }: { initial?: string }) {
  const [value, setValue] = useState(initial), [saved, setSaved] = useState('');
  return <form aria-label="Context override editor" onSubmit={e => { e.preventDefault(); setSaved(String(objectInput(value).question ?? 'Default question retained')); }}><ContextBlockInputs blocks={blocks} value={value} onChange={setValue} /><button className="primary">Compile overrides</button>{saved && <p role="status">{saved}</p>}</form>;
}
function Board({ narrow = false }: { narrow?: boolean }) {
  const [inspectorOpen, setInspectorOpen] = useState(true);
  return <div className={narrow ? 'workbench-board workbench-narrow' : 'workbench-board'}>
    <section className="workbench-tile"><h2>01 · Preflight checklist</h2><PreflightChecklist report={blocked} focusOnReport={false} /></section>
    <section className="workbench-tile"><h2>02 · Resource picker and version chip</h2><PickerDemo initial="4" /></section>
    <section className="workbench-tile"><h2>03 · Metric comparison</h2><MetricComparison metrics={metrics} baseline={baseline} /></section>
    <section className="workbench-tile"><h2>04 · Release gate checklist</h2><ReleaseGateChecklist criteria={gates} state="blocked" evidenceHref="#eval-1" /></section>
    <section className="workbench-tile"><h2>05 · Lineage panel</h2><LineagePanel paths={lineage} /></section>
    <section className="workbench-tile"><h2>06 · Inspector panel</h2>{inspectorOpen ? <InspectorPanel title="Research worker" focusOnOpen={false} onClose={() => setInspectorOpen(false)}><dl className="wb-facts"><div><dt>Registration state</dt><dd>Idle</dd></div><div><dt>Last heartbeat</dt><dd>Not reported</dd></div></dl></InspectorPanel> : <button onClick={() => setInspectorOpen(true)}>Inspect worker</button>}</section>
    <section className="workbench-tile"><h2>07 · Context block editor</h2><ContextDemo /></section>
    <section className="workbench-tile"><h2>08 · Retrieval evidence card</h2><RetrievalEvidenceCard chunk={chunk} query="dataset splits" rank={1} /></section>
  </div>;
}
export const ComponentBoard: Story = { render: () => <Board /> };
export const DarkBoard: Story = { parameters: { demoTheme: 'dark' }, render: () => <Board /> };
export const NarrowBoard: Story = { render: () => <Board narrow />, play: async ({ canvasElement }) => {
  const board = canvasElement.querySelector('.workbench-narrow')!;
  await expect(board.scrollWidth).toBeLessThanOrEqual(board.clientWidth + 1); verified(canvasElement);
} };
export const PreflightReady: Story = { render: () => <PreflightChecklist report={approved} onLaunch={() => {}} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByRole('button', { name: 'Launch fine-tuning' })).toBeEnabled();
  await userEvent.click(canvas.getByText(/Encoded training samples/)); await userEvent.click(canvas.getByText('Exact token IDs')); await expect(canvas.getByText('42', { selector: 'code' })).toBeVisible(); verified(canvasElement);
} };
export const PreflightBlocked: Story = { render: () => <PreflightChecklist report={blocked} onLaunch={() => {}} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByRole('button', { name: 'Launch fine-tuning' })).toBeDisabled(); await expect(canvas.getByText('Choose a policy with sufficient remaining steps.', { exact: false })).toBeVisible(); verified(canvasElement);
} };
export const PreflightExpired: Story = { render: () => <PreflightChecklist report={{ ...approved, expires_in_seconds: 0 }} onLaunch={() => {}} onRefresh={() => {}} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByText('Preview expired')).toBeVisible(); await expect(canvas.getByRole('button', { name: 'Launch fine-tuning' })).toBeDisabled(); verified(canvasElement);
} };
export const PreflightMissingExpiry: Story = { render: () => <PreflightChecklist report={{ ...approved, expires_in_seconds: NaN }} onLaunch={() => {}} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByText('Expiry not reported')).toBeVisible(); await expect(canvas.getByRole('button', { name: 'Launch fine-tuning' })).toBeDisabled(); verified(canvasElement);
} };
function ExpiringDemo() {
  const [report, setReport] = useState(() => ({ ...approved, expires_in_seconds: 1 }));
  return <PreflightChecklist report={report} onLaunch={() => {}} onRefresh={() => setReport({ ...approved })} />;
}
export const PreflightLiveExpiry: Story = { render: () => <ExpiringDemo />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await waitFor(() => expect(canvas.getByRole('button', { name: 'Launch fine-tuning' })).toBeDisabled(), { timeout: 4000 });
  await userEvent.click(canvas.getByRole('button', { name: 'Refresh preflight' })); await waitFor(() => expect(canvas.getByRole('button', { name: 'Launch fine-tuning' })).toBeEnabled()); verified(canvasElement);
} };
export const ResourceSelection: Story = { render: () => <PickerDemo />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await userEvent.type(canvas.getByRole('searchbox', { name: 'Search candidate model' }), '000000000004');
  await userEvent.clear(canvas.getByRole('searchbox')); await userEvent.type(canvas.getByRole('searchbox'), 'r4');
  await expect(canvas.getAllByRole('option')).toHaveLength(2);
  await userEvent.selectOptions(canvas.getByLabelText('Candidate model', { exact: true }), '4');
  await userEvent.clear(canvas.getByRole('searchbox')); await userEvent.type(canvas.getByRole('searchbox'), 'no matching model');
  await expect(canvas.getByLabelText('Candidate model', { exact: true })).toHaveValue('4');
  await userEvent.click(canvas.getByRole('button', { name: 'Use selected revision' })); await expect(canvas.getByText('Selected resource value: 4')).toBeVisible();
  await userEvent.clear(canvas.getByRole('searchbox')); await expect(canvas.getByRole('option', { name: /Imported model/ })).toBeDisabled();
  await userEvent.click(canvas.getByText('Unavailable choices and reasons')); await expect(canvas.getByText(/This format has no installed/)).toBeVisible();
  await userEvent.hover(canvas.getByRole('button', { name: 'Copy ID for Support assistant' }));
  await expect(within(await within(document.body).findByRole('tooltip')).getByText(resources[0].id, { selector: 'code' })).toBeVisible(); verified(canvasElement);
} };
export const SavedResourceUnavailable: Story = { render: () => <PickerDemo initial="deleted-resource" />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByLabelText('Candidate model', { exact: true })).toHaveAttribute('aria-invalid', 'true');
  await userEvent.click(canvas.getByRole('button', { name: 'Use selected revision' })); await expect(canvas.queryByRole('status')).not.toBeInTheDocument();
  await userEvent.selectOptions(canvas.getByLabelText('Candidate model', { exact: true }), '4'); await userEvent.click(canvas.getByRole('button', { name: 'Use selected revision' })); await expect(canvas.getByText('Selected resource value: 4')).toBeVisible(); verified(canvasElement);
} };
export const DisabledResourceSelection: Story = { render: () => <PickerDemo initial="4" disabled /> };
function LoadingPickerDemo() {
  const [loading, setLoading] = useState(true);
  return <><ResourcePicker label="Candidate model" value="4" onChange={() => {}} loading={loading} options={loading ? [] : resources} /><button onClick={() => setLoading(false)}>Finish inventory load</button></>;
}
export const ResourceInventoryLoading: Story = { render: () => <LoadingPickerDemo />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement), picker = canvas.getByRole('combobox', { name: 'Candidate model' });
  await expect(picker).toBeDisabled(); await expect(picker).not.toHaveAttribute('aria-invalid', 'true');
  await expect(canvas.getByRole('status')).toHaveTextContent('Your saved selection is retained');
  await expect(canvas.queryByText('Saved resource unavailable')).not.toBeInTheDocument();
  await userEvent.click(canvas.getByRole('button', { name: 'Finish inventory load' }));
  await expect(picker).toBeEnabled(); await expect(picker).toHaveValue('4'); verified(canvasElement);
} };
export const MetricsWithBaseline: Story = { render: () => <MetricComparison metrics={metrics} baseline={baseline} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByRole('row', { name: /Loss all/ })).toHaveTextContent('-0.1');
  await expect(canvas.getByRole('row', { name: /Accuracy empty/ })).toHaveTextContent('0'); await expect(canvas.getByRole('row', { name: /baseline_only/ })).toHaveTextContent('Unavailable'); verified(canvasElement);
} };
export const MetricsWithoutBaseline: Story = { render: () => <MetricComparison metrics={metrics} /> };
export const ReleaseGates: Story = { render: () => <ReleaseGateChecklist criteria={gates} state="blocked" evidenceHref="#eval-1" />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); for (const status of ['Passed', 'Failed', 'Missing evidence']) await expect(canvas.getByText(status, { exact: true })).toBeVisible(); await expect(canvas.getByRole('link', { name: 'Open exact evaluation' })).toHaveAttribute('href', '#eval-1'); verified(canvasElement);
} };
export const RecordedLineage: Story = { render: () => <LineagePanel paths={lineage} />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByRole('link', { name: 'Held-out evaluation' })).toHaveAttribute('href', '#eval-1'); await expect(canvas.getByText('Missing relationships are left unconnected.', { exact: false })).toBeVisible(); verified(canvasElement);
} };
export const InspectorKeyboard: Story = { render: () => <InspectorDemo />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement), trigger = canvas.getByRole('button', { name: 'Inspect worker' });
  await userEvent.click(trigger); const inspector = canvas.getByRole('complementary', { name: 'Research worker' }); await expect(inspector).toHaveFocus();
  await userEvent.keyboard('{Escape}'); await expect(canvas.queryByRole('complementary')).not.toBeInTheDocument(); await expect(trigger).toHaveFocus();
  await userEvent.click(trigger); await userEvent.click(canvas.getByRole('button', { name: 'Close details' })); await expect(trigger).toHaveFocus(); verified(canvasElement);
} };
export const ContextEditing: Story = { render: () => <ContextDemo />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement), input = canvas.getByLabelText('Question template'); await userEvent.clear(input); await userEvent.click(canvas.getByRole('button', { name: 'Save context' })); await expect(canvas.queryByRole('status')).not.toBeInTheDocument();
  await userEvent.type(input, '  Exact question\n'); await userEvent.click(canvas.getByRole('button', { name: 'Save context' })); await expect(canvas.getByRole('status')).toHaveTextContent('Context saved.'); await expect(input).toHaveValue('  Exact question\n'); verified(canvasElement);
} };
export const ContextOverrides: Story = { render: () => <OverridesDemo />, play: async ({ canvasElement }) => {
  const canvas = within(canvasElement); await expect(canvas.getByLabelText('Question template override')).toBeDisabled();
  await userEvent.click(canvas.getByRole('checkbox', { name: 'Override Question template' })); await userEvent.clear(canvas.getByLabelText('Question template override')); await userEvent.type(canvas.getByLabelText('Question template override'), '  Exact override\n');
  await userEvent.click(canvas.getByRole('button', { name: 'Compile overrides' })); await expect(canvas.getByRole('status')).toHaveTextContent('Exact override');
  await userEvent.click(canvas.getByRole('checkbox', { name: 'Override Question template' })); await userEvent.click(canvas.getByRole('button', { name: 'Compile overrides' })); await expect(canvas.getByRole('status')).toHaveTextContent('Default question retained'); verified(canvasElement);
} };
export const StructuredContextDraft: Story = { render: () => <OverridesDemo initial='{"question":{"text":"preserved"},"extra":false}' /> };
export const CompilationOmissions: Story = { render: () => <ContextBlockEditor blocks={blocks.map(block => ({ ...block, status: block.key === 'evidence' ? 'Omitted' : 'Included', tokenCount: block.key === 'evidence' ? undefined : 12 }))} /> };
export const RetrievalEvidence: Story = { render: () => <RetrievalEvidenceCard chunk={chunk} rank={1} query="DATASET splits" />, play: async ({ canvasElement }) => {
  await expect(within(canvasElement).getByRole('heading', { name: 'Dataset preparation guide' })).toBeVisible();
  const canvas = within(canvasElement); await expect(canvas.getByText('Lexical score: 0')).toBeVisible(); await expect(canvasElement.querySelectorAll('mark').length).toBeGreaterThan(0);
  await userEvent.click(canvas.getByText('Full source text')); await expect(canvas.getByText(/<script>This is source text/)).toBeVisible(); await expect(canvasElement.querySelector('.evidence-full-text script')).toBeNull();
  await userEvent.click(canvas.getByText('Source metadata and identity')); await expect(canvas.getByText('Revision', { exact: true })).toBeVisible(); verified(canvasElement);
} };
export const EmptyEvidence: Story = { render: () => <><MetricComparison metrics={[]} /><ReleaseGateChecklist criteria={[]} state="unknown" /><LineagePanel paths={[]} /><ContextBlockEditor blocks={[]} /></> };
