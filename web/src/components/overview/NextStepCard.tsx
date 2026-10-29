import { ArrowRight } from 'lucide-react';
import { Button, Card, JourneySteps, LinkButton } from '../ui';
import { FINE_TUNE_STAGES, stageIndex } from '../../api/journey';
import type { ExperimentAction } from '../../api/improvement';

export function NextStepCard({ action, loading, error, hasRuns, onNavigate }: { action: ExperimentAction; loading: boolean; error: boolean; hasRuns: boolean; onNavigate: (page: string) => void }) {
  return <Card padded className="next-step" aria-labelledby="next-step-title">
    <div><h2 id="next-step-title">{loading ? 'Finding your next step…' : action.title}</h2><p>{loading ? 'Checking saved training and comparison records.' : action.description}</p></div>
    <JourneySteps steps={FINE_TUNE_STAGES} current={stageIndex(action.stage)} label="Fine-tuning journey" />
    {error ? <p role="status">Your latest run could not be verified. Retry the unavailable data below before continuing.</p>
      : !loading && <div data-ui="actions"><LinkButton variant="primary" href={action.href}>{action.label} <ArrowRight size={16} aria-hidden="true" /></LinkButton>{hasRuns && <Button type="button" onClick={() => onNavigate('Training')}>New training run</Button>}</div>}
  </Card>;
}
