import { useEffect, useState } from 'react';
import { BookOpen, Layers } from 'lucide-react';
import { Button } from './ui';
import { RegisterModelVersionModal, RegisterTokenizerModal } from './PrerequisiteModals';
import type { RegisteredModelVersion, TokenizerVersion } from '../api/resources';

export function PrerequisiteActions({ token, onTokenizer, onVersion, openTokenizer = 0 }: {
  token: string;
  onTokenizer?: (tokenizer: TokenizerVersion) => void;
  onVersion?: (version: RegisteredModelVersion) => void;
  openTokenizer?: number;
}) {
  const [tokenizerOpen, setTokenizerOpen] = useState(false);
  const [versionOpen, setVersionOpen] = useState(false);
  useEffect(() => { if (openTokenizer) setTokenizerOpen(true); }, [openTokenizer]);
  return <>
    <Button type="button" disabled={!token.trim()} onClick={() => setTokenizerOpen(true)}><BookOpen size={14} aria-hidden="true" /> Tokenizer</Button>
    <Button type="button" disabled={!token.trim()} onClick={() => setVersionOpen(true)}><Layers size={14} aria-hidden="true" /> Model version</Button>
    <RegisterTokenizerModal token={token} isOpen={tokenizerOpen} onClose={() => setTokenizerOpen(false)} onSuccess={tokenizer => { setTokenizerOpen(false); onTokenizer?.(tokenizer); }} />
    <RegisterModelVersionModal token={token} isOpen={versionOpen} onClose={() => setVersionOpen(false)} onSuccess={version => { setVersionOpen(false); onVersion?.(version); }} />
  </>;
}
