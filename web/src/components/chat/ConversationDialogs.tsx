import { useId } from 'react';
import { Button, Dialog, TextControl } from '../ui';

/** Rename and delete dialogs for the selected conversation. */
export function ConversationDialogs({ title, busy, renameOpen, renameTitle, deleteOpen, onRenameTitle, onRename, onCloseRename, onDelete, onCloseDelete }: {
  title?: string; busy: boolean; renameOpen: boolean; renameTitle: string; deleteOpen: boolean;
  onRenameTitle(value: string): void; onRename(event: React.FormEvent): void; onCloseRename(): void; onDelete(): void; onCloseDelete(): void;
}) {
  const renameFormId = useId();
  return <>
    <Dialog title="Rename conversation" open={renameOpen} onClose={onCloseRename}
      footer={<><Button type="button" disabled={busy} onClick={onCloseRename}>Cancel</Button><Button form={renameFormId} type="submit" variant="primary" disabled={busy || !renameTitle.trim()}>Rename</Button></>}>
      <form id={renameFormId} data-ui="form" onSubmit={onRename}><TextControl label="New conversation title" maxLength={180} value={renameTitle} onChange={event => onRenameTitle(event.target.value)} disabled={busy} required autoFocus /></form>
    </Dialog>
    <Dialog title="Delete conversation" description={title ? `Delete “${title}” from saved conversations? Review and accounting records keep their own history.` : undefined} open={deleteOpen} onClose={onCloseDelete}
      footer={<><Button type="button" disabled={busy} onClick={onCloseDelete}>Keep conversation</Button><Button type="button" variant="primary" disabled={busy} onClick={onDelete}>Delete conversation</Button></>}>
      <p className="muted">The transcript and its comparisons are removed from this project.</p>
    </Dialog>
  </>;
}
