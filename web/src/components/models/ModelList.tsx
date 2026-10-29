import { Badge, Button, StatusBadge } from '../ui';
import { taskLabel, versionsOf, type Model, type ModelVersion } from '../../api/models';

/** One row per model: name, one line, task badges and the latest version state. */
export function ModelList({ models, versions, selected, onSelect }: { models: Model[]; versions: ModelVersion[]; selected: string | null; onSelect(id: string): void }) {
  if (!models.length) return null;
  return <ul className="models-list">
    {models.map(model => {
      const own = versionsOf(model, versions); const latest = own[0]; const active = model.model_id === selected;
      return <li key={model.model_id} className={active ? 'models-row models-row-selected' : 'models-row'}>
        <div className="models-row-main">
          <h3>{model.name}</h3>
          <p>{model.description || 'No description.'}</p>
          {model.intended_tasks.length > 0 && <div data-ui="actions">{model.intended_tasks.map(task => <Badge key={task}>{taskLabel(task)}</Badge>)}</div>}
        </div>
        <div className="models-row-meta">
          {latest ? <><span>{own.length === 1 ? '1 version' : `${own.length} versions`} · latest r{latest.revision_no}</span><StatusBadge status={latest.state} /></> : <span>No versions yet</span>}
          <Button type="button" size="sm" variant={active ? 'primary' : 'secondary'} aria-label={`Inspect ${model.name}`} aria-pressed={active} onClick={() => onSelect(model.model_id)}>Inspect</Button>
        </div>
      </li>;
    })}
  </ul>;
}
