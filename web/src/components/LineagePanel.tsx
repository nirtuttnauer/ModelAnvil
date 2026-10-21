import { ArrowRight } from 'lucide-react';
import { VersionChip, type ResourceOption } from './ResourcePicker';
import './workbench-components.css';

export interface LineagePath { label: string; nodes: (Omit<ResourceOption, 'value'> & { kind: string })[] }
export function LineagePanel({ paths, emptyMessage = 'No accessible lineage relationships recorded.' }: { paths: LineagePath[]; emptyMessage?: string }) {
  return <section className="lineage-panel" aria-label="Resource lineage"><h3>Lineage</h3><p className="wb-muted">Each path shows recorded relationships. Missing relationships are left unconnected.</p>
    {paths.length ? paths.map((path, index) => <div className="lineage-path" key={index}><h4>{path.label}</h4><ol>{path.nodes.map((node, i) => <li key={`${node.kind}:${node.id}:${i}`}>
      {i > 0 && <ArrowRight size={18} aria-hidden="true" className="lineage-arrow" />}<div className="lineage-node"><span className="wb-muted">{node.kind}</span><VersionChip {...node} /></div>
    </li>)}</ol></div>) : <p className="wb-empty">{emptyMessage}</p>}
  </section>;
}
