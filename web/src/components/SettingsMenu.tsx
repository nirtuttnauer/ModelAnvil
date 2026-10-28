import type { ReactNode } from 'react';
import { KeyRound, LogOut, RefreshCw, Settings2 } from 'lucide-react';
import { Button } from './ui';
import { Menu, MenuSection } from './primitives';
import { ThemeControl } from './ThemeControl';

type OrganizationOption = { tenant_id: string; name: string };

/** Header settings menu: appearance, organization scope, workspace actions, API status and build identity. */
export function SettingsMenu({ tenantName, organizations, currentOrganization, organizationDisabled, onSelectOrganization, onRefresh, isSession, connectionBusy, onConnection, onSignOut, apiStatus, about }: {
  tenantName: string; organizations: OrganizationOption[]; currentOrganization: OrganizationOption | null; organizationDisabled: boolean;
  onSelectOrganization(id: string): void; onRefresh(): void; isSession: boolean; connectionBusy: boolean; onConnection(): void; onSignOut(): void;
  apiStatus: string; about: ReactNode;
}) {
  const statusClass = apiStatus === 'API unavailable' ? 'offline' : apiStatus === 'Checking API' ? 'checking' : '';
  return <Menu label="Settings" icon={<Settings2 size={18} aria-hidden="true" />} className="settings-menu">
    <MenuSection label="Appearance"><ThemeControl /></MenuSection>
    <MenuSection label="Organization">
      <select aria-label="Organization" value={currentOrganization?.tenant_id || ''} disabled={organizationDisabled} onChange={event => onSelectOrganization(event.target.value)}>
        {!currentOrganization && <option value="" disabled>{tenantName}</option>}
        {organizations.map(organization => <option key={organization.tenant_id} value={organization.tenant_id}>{organization.name}</option>)}
        <option value="connect-organization">Connect organization…</option>
      </select>
    </MenuSection>
    <MenuSection label="Workspace">
      <Button type="button" variant="quiet" onClick={onRefresh}><RefreshCw size={16} aria-hidden="true" />Refresh workspace</Button>
      {isSession
        ? <Button type="button" variant="quiet" disabled={connectionBusy} onClick={onSignOut}><LogOut size={16} aria-hidden="true" />Sign out</Button>
        : <Button type="button" variant="quiet" disabled={connectionBusy} onClick={onConnection}><KeyRound size={16} aria-hidden="true" />Connection</Button>}
      <p className="settings-status"><span className={`status-dot ${statusClass}`} aria-hidden="true" />{apiStatus}</p>
    </MenuSection>
    <MenuSection label="About">{about}</MenuSection>
  </Menu>;
}
