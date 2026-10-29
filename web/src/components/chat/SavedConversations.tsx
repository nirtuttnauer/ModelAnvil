import { useState } from 'react';
import { Disclosure, Select, TextControl } from '../ui';

/** Search and pick a saved conversation; "New conversation" clears the selection. */
export function SavedConversations({ conversations, selectedId, locked, open, onToggle, onSelect }: {
  conversations: Array<{ conversation_id: string; title: string }>; selectedId: string; locked: boolean; open: boolean;
  onToggle(open: boolean): void; onSelect(conversationId: string): void;
}) {
  const [query, setQuery] = useState('');
  return <Disclosure summary="Saved conversations" variant="quiet" open={open} onToggle={event => onToggle(event.currentTarget.open)}>
    <div data-ui="field-grid" className="chat-settings-grid">
      <TextControl label="Search saved conversations" value={query} onChange={event => setQuery(event.target.value)} disabled={locked} />
      <Select label="Saved conversation" value={selectedId} disabled={locked} onChange={event => onSelect(event.target.value)}>
        <option value="">New conversation</option>
        {conversations.filter(c => c.title.toLowerCase().includes(query.toLowerCase())).map(c => <option key={c.conversation_id} value={c.conversation_id}>{c.title}</option>)}
      </Select>
    </div>
  </Disclosure>;
}
