import type { ElementType } from 'react';
import { ChevronDown } from 'lucide-react';
import { NavigationItem } from './ui';

export type NavigationGroup = { label: string; names: string[] };
export type NavigationPage = { name: string; icon: ElementType };

/** Light workspace rail: logo, the primary group, and the other groups behind one disclosure. */
export function NavigationRail({ groups, pages, selected, advancedOpen, onAdvancedToggle, onNavigate }: {
  groups: NavigationGroup[]; pages: NavigationPage[]; selected: string; advancedOpen: boolean;
  onAdvancedToggle(open: boolean): void; onNavigate(name: string): void;
}) {
  const base = import.meta.env.BASE_URL;
  const renderGroup = (group: NavigationGroup) => <div className="nav-group" key={group.label}>
    <p className="nav-label">{group.label}</p>
    {pages.filter(page => group.names.includes(page.name)).map(({ name, icon: Icon }) => (
      <NavigationItem key={name} title={name} selected={selected === name} icon={<Icon size={18} aria-hidden="true" />} aria-label={name} onClick={() => onNavigate(name)}>{name}</NavigationItem>
    ))}
  </div>;
  return <aside className="navigation-rail" id="workspace-navigation" aria-label="Workspace navigation">
    <a className="brand" href="#overview" aria-label="ModelAnvil overview">
      <img className="brand-logo brand-logo-light" src={`${base}brand/modelanvil-logo.svg`} alt="" width="1088" height="240" />
      <img className="brand-logo brand-logo-dark" src={`${base}brand/modelanvil-logo-reversed.svg`} alt="" width="1088" height="240" />
    </a>
    <nav aria-label="Main navigation">
      {groups.slice(0, 1).map(renderGroup)}
      <details className="advanced-navigation" open={advancedOpen} onToggle={event => onAdvancedToggle(event.currentTarget.open)}>
        <summary>Advanced workspace <ChevronDown size={16} aria-hidden="true" /></summary>
        <div className="nav-groups">{groups.slice(1).map(renderGroup)}</div>
      </details>
    </nav>
  </aside>;
}
