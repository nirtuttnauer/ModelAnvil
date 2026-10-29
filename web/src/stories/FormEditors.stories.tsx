import { useState } from 'react';
import type { Meta, StoryObj } from '@storybook/react-vite';
import { expect, userEvent, within } from 'storybook/test';
import { ConfigFields, ObjectFields, RecordListEditor, VerifierFields } from '../components/FormEditors';
import { DataInspector } from '../components/DataInspector';
import { alignmentFields, evaluationFields, objectInput, preferenceFields, recordsInput, sampleFields, spanFields, structuredInput, type FormField } from '../components/form-data';
import { preferencePairs } from '../api/alignment';
import '../design-system/index.css';
import './form-editor-stories.css';

const meta = {
  title: 'ModelAnvil/Components/Input forms', parameters: { layout: 'fullscreen' },
  beforeEach({ parameters }) { document.documentElement.dataset.theme = parameters.demoTheme ?? 'light'; delete document.getElementById('storybook-root')?.dataset.demoVerified; },
  decorators: [(Story) => <div className="form-story-canvas"><Story /></div>],
} satisfies Meta;
export default meta;
type Story = StoryObj<typeof meta>;

function ObjectDemo({ initial = '{"prompt":"Summarize the source.","options":{"stream":false,"attempts":0}}', tokens = false, rubric = false, disabled = false }: { initial?: string; tokens?: boolean; rubric?: boolean; disabled?: boolean }) {
  const [value, setValue] = useState(initial), [result, setResult] = useState<unknown>(), [error, setError] = useState('');
  return <form aria-label="Field builder demo" onSubmit={e => { e.preventDefault(); try { setResult(structuredInput(value)); setError(''); } catch (error) { setError(String(error)); } }}>
    <ObjectFields title={tokens ? 'Special tokens' : rubric ? 'Rubric scores' : 'Job inputs'} description={tokens ? 'Keep token symbols exactly as the model expects.' : 'Use labeled fields, groups, and lists to describe your inputs.'} value={value} onChange={setValue} disabled={disabled} textOnly={tokens} defaultKind={rubric ? 'number' : 'text'} nameLabel={tokens ? 'Token name' : rubric ? 'Criterion' : 'Field name'} valueLabel={tokens ? 'Token symbol' : rubric ? 'Score' : 'Value'} />
    <button className="primary" disabled={disabled}>Save inputs</button>{error && <p role="alert">{error}</p>}{result !== undefined && <><p role="status">Inputs saved.</p><DataInspector title="Saved inputs" value={result} /></>}
  </form>;
}

function RecordsDemo({ title, itemName, fields, maximum, uniqueKey, initial = '[]', preferences = false }: { title: string; itemName: string; fields: FormField[]; maximum?: number; uniqueKey?: string; initial?: string; preferences?: boolean }) {
  const [value, setValue] = useState(initial), [result, setResult] = useState<unknown>(), [error, setError] = useState('');
  return <form aria-label={`${title} demo`} onSubmit={e => { e.preventDefault(); try { const rows = recordsInput(value, fields, maximum ?? Infinity, uniqueKey); setResult(preferences ? preferencePairs(JSON.stringify(rows)) : rows); setError(''); } catch (error) { setError((error as Error).message); } }}>
    <RecordListEditor title={title} itemName={itemName} fields={fields} maximum={maximum} uniqueKey={uniqueKey} value={value} onChange={setValue} /><button className="primary">Save records</button>
    {error && <p role="alert">{error}</p>}{result !== undefined && <><p role="status">Records saved.</p><DataInspector title="Saved records" value={result} /></>}
  </form>;
}

function SettingsDemo() {
  const [algorithm, setAlgorithm] = useState('dpo'), [params, setParams] = useState('{"learning_rate":0.05}'), [verifier, setVerifier] = useState('{"type":"exact_match"}'), [result, setResult] = useState<unknown>();
  return <form aria-label="Alignment settings demo" onSubmit={e => { e.preventDefault(); setResult({ hyperparameters: objectInput(params), verifier_spec: objectInput(verifier) }); }}>
    <label>Algorithm<select value={algorithm} onChange={e => setAlgorithm(e.target.value)}><option value="dpo">Direct preference optimization</option><option value="reward_model">Reward model</option><option value="ppo_rlhf">PPO RLHF</option><option value="verifier_rl">Verifier guided RL</option></select></label>
    <ConfigFields title="Optimizer settings" fields={alignmentFields(algorithm)} value={params} onChange={setParams} />
    {algorithm === 'verifier_rl' && <VerifierFields value={verifier} onChange={setVerifier} />}<button className="primary">Save settings</button>{result !== undefined && <><p role="status">Settings saved.</p><DataInspector title="Saved settings" value={result} /></>}
  </form>;
}

export const PayloadBuilder: Story = {
  render: () => <ObjectDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Save inputs' }));
    await expect(canvas.getByText('No', { exact: true, selector: '.data-boolean' })).toBeVisible();
    await expect(canvas.getByText('0', { exact: true })).toBeVisible();
    await expect(canvas.getByRole('status')).toHaveTextContent('Inputs saved.');
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const EvaluationCases: Story = {
  render: () => <RecordsDemo key="Evaluation cases" title="Evaluation cases" itemName="Case" fields={evaluationFields} maximum={64} uniqueKey="case_id" initial='[{"case_id":"case-1","input_prompt":"Hello","expected_output":"hello","slice":"general","source_group_id":"held-out"}]' />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Add case' }));
    const second = within(canvas.getByRole('group', { name: 'Case 2' }));
    await userEvent.clear(second.getByLabelText('Case ID'));
    await userEvent.type(second.getByLabelText('Case ID'), 'case-1');
    await expect(second.getByLabelText('Case ID')).toHaveAttribute('aria-invalid', 'true');
    await userEvent.click(canvas.getByRole('button', { name: 'Save records' }));
    await expect(canvas.queryByText('Records saved.')).not.toBeInTheDocument();
    await userEvent.clear(second.getByLabelText('Case ID'));
    await userEvent.type(second.getByLabelText('Case ID'), 'case-2');
    await userEvent.type(second.getByLabelText('Input prompt'), 'Keep whitespace.\n');
    await userEvent.type(second.getByLabelText('Expected response'), ' exact response ');
    await userEvent.click(canvas.getByRole('button', { name: 'Remove case 1' }));
    await expect(canvas.getByLabelText('Case ID')).toHaveValue('case-2');
    await expect(canvas.getByLabelText('Expected response')).toHaveValue(' exact response ');
    await userEvent.click(canvas.getByRole('button', { name: 'Save records' }));
    await expect(canvas.getByText('Records saved.')).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const Preferences: Story = {
  render: () => <RecordsDemo key="Preference pairs" title="Preference pairs" itemName="Preference pair" fields={preferenceFields} maximum={32} preferences />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole('button', { name: 'Add preference pair' }));
    await userEvent.type(canvas.getByLabelText('Prompt'), 'Say a');
    await userEvent.type(canvas.getByLabelText('Preferred response'), 'a');
    await userEvent.type(canvas.getByLabelText('Rejected response'), 'a');
    await userEvent.click(canvas.getByRole('button', { name: 'Save records' }));
    await expect(canvas.getByRole('alert')).toHaveTextContent('Chosen and rejected responses must differ.');
    await userEvent.clear(canvas.getByLabelText('Rejected response'));
    await userEvent.type(canvas.getByLabelText('Rejected response'), 'b');
    await userEvent.click(canvas.getByRole('button', { name: 'Save records' }));
    await expect(canvas.getByText('Records saved.')).toBeVisible();
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const OptimizerAndVerifier: Story = {
  render: () => <SettingsDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.clear(canvas.getByLabelText('Learning rate'));
    await userEvent.type(canvas.getByLabelText('Learning rate'), '0.3');
    await userEvent.tab();
    await expect(canvas.getByLabelText('Learning rate')).toHaveAttribute('aria-invalid', 'true');
    await userEvent.clear(canvas.getByLabelText('Learning rate'));
    await userEvent.type(canvas.getByLabelText('Learning rate'), '0.01');
    await userEvent.selectOptions(canvas.getByLabelText('Algorithm'), 'verifier_rl');
    await expect(canvas.queryByLabelText('DPO beta')).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByLabelText('Verification method'), 'numeric_tolerance');
    await userEvent.type(canvas.getByLabelText('Numeric tolerance'), '0');
    await userEvent.click(canvas.getByRole('button', { name: 'Save settings' }));
    await expect(canvas.getByRole('status')).toHaveTextContent('Settings saved.');
    canvasElement.dataset.demoVerified = 'passed';
  },
};
export const TokenSymbols: Story = { render: () => <ObjectDemo tokens initial='{"bos_token":"<s>","eos_token":"</s>","pad_token":"<pad>"}' /> };
export const SourceSamples: Story = { render: () => <RecordsDemo key="Source samples" title="Source samples" itemName="Sample" fields={sampleFields} maximum={500} uniqueKey="id" initial='[{"id":"sample-1","text":"An original source passage."}]' /> };
export const EntitySpans: Story = { render: () => <RecordsDemo key="Entity spans" title="Entity spans" itemName="Entity span" fields={spanFields} initial='[{"start":0,"end":4,"label":"Person"}]' /> };
export const RubricScores: Story = { render: () => <ObjectDemo rubric initial='{"accuracy":4,"clarity":3}' /> };
export const DamagedDraft: Story = { render: () => <ObjectDemo initial="incomplete saved input" />, play: async ({ canvasElement }) => { const canvas = within(canvasElement); await expect(canvas.getByRole('alert')).toHaveTextContent('Saved fields could not be restored.'); await userEvent.click(canvas.getByRole('button', { name: 'Clear saved fields' })); await expect(canvas.queryByRole('alert')).not.toBeInTheDocument(); await userEvent.click(canvas.getByRole('button', { name: 'Save inputs' })); await expect(canvas.getByRole('status')).toHaveTextContent('Inputs saved.'); canvasElement.dataset.demoVerified = 'passed'; } };
export const Disabled: Story = { render: () => <ObjectDemo disabled /> };
export const Narrow: Story = { render: () => <div className="form-story-narrow"><RecordsDemo key="Evaluation cases" title="Evaluation cases" itemName="Case" fields={evaluationFields} maximum={64} uniqueKey="case_id" initial='[{"case_id":"case-1","input_prompt":"Summarize this source.","expected_output":"A clear, grounded answer.","slice":"general","source_group_id":"held-out"}]' /></div> };
export const Dark: Story = { ...OptimizerAndVerifier, parameters: { demoTheme: 'dark' } };
