import { Disclosure, LinkButton } from '../ui';
import { resourceHash } from '../../api/resource-routes';
import { runHash } from '../../api/runs';
import { linkId, type RunDetail } from '../../api/run-detail';

/** Every record this run pinned, produced or was executed under. */
export function RunLinks({ links }: { links: RunDetail['links'] }) {
  return <Disclosure summary="Links" variant="card">
    <div data-ui="actions">
      {links.job && <LinkButton href={runHash('job', linkId(links.job))}>Job</LinkButton>}
      {links.training_run && <LinkButton href={runHash('training', linkId(links.training_run))}>Training run</LinkButton>}
      {links.output_model_version && <LinkButton href={resourceHash('model-version', linkId(links.output_model_version))}>Trained model</LinkButton>}
      {links.base_model_version && <LinkButton href={resourceHash('model-version', linkId(links.base_model_version))}>Base model version</LinkButton>}
      {links.recovery_parent && <LinkButton href={runHash('training', linkId(links.recovery_parent))}>Parent run</LinkButton>}
      {links.model_version && <LinkButton href={resourceHash('model-version', linkId(links.model_version))}>Model version</LinkButton>}
      {links.dataset_revision && <LinkButton href={resourceHash('dataset-revision', linkId(links.dataset_revision))}>Dataset version</LinkButton>}
      {Array.isArray(links.evaluation_runs) && links.evaluation_runs.map((id, index) => <LinkButton key={id} href={runHash('evaluation', id)}>Evaluation run {index + 1}</LinkButton>)}
      <LinkButton variant="quiet" href="#infrastructure">Infrastructure</LinkButton>
      <LinkButton variant="quiet" href="#budgets">Budgets</LinkButton>
      <LinkButton variant="quiet" href="#audit">Audit</LinkButton>
    </div>
  </Disclosure>;
}
