import { Button } from './ui';
import { Children, isValidElement, useState, type ComponentProps } from 'react';
import { Check, Copy } from 'lucide-react';
import Markdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { structuredResponse } from '../api/response-content';
import { DataInspector, TextContent } from './DataInspector';
import './markdown-response.css';

export function CopyResponseButton({ text, label = 'Copy response' }: { text: string; label?: string }) {
  const [result, setResult] = useState<{ text: string; status: 'copying' | 'copied' | 'failed' } | null>(null);
  const status = result?.text === text ? result.status : null;
  async function copy() {
    const value = text;
    setResult({ text: value, status: 'copying' });
    try {
      await navigator.clipboard.writeText(value);
      setResult({ text: value, status: 'copied' });
    } catch {
      setResult({ text: value, status: 'failed' });
    }
  }
  return <div className="response-copy">
    <Button type="button" aria-label={label} disabled={!text || result?.status === 'copying'} onClick={() => void copy()}>
      {status === 'copied' ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
      {label}
    </Button>
    <span role="status">{status === 'copied' ? `${label === 'Copy code' ? 'Code' : 'Response'} copied.` : status === 'failed' ? 'Copy unavailable. Select the text to copy it.' : ''}</span>
  </div>;
}

const components: Components = {
  pre({ children }) {
    const child = Children.toArray(children)[0];
    const code = isValidElement<ComponentProps<'code'>>(child) ? child : null;
    const value = typeof code?.props.children === 'string' ? code.props.children.replace(/\n$/, '') : '';
    const language = code?.props.className?.replace(/^language-/, '') || 'Code';
    return <div className="response-code-block">
      <div className="response-code-toolbar"><span>{language}</span><CopyResponseButton text={value} label="Copy code" /></div>
      <pre tabIndex={0} aria-label={`${language} code block`}>{children}</pre>
    </div>;
  },
  a({ href, children }) {
    return href ? <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span>{children}</span>;
  },
  // Model-generated images stay links instead of issuing remote requests automatically.
  img({ src, alt }) {
    return src ? <a href={src} target="_blank" rel="noopener noreferrer">{alt || 'Image'}</a> : <span>{alt || 'Image'}</span>;
  },
  table({ children }) {
    return <div className="response-table-scroll" tabIndex={0} role="region" aria-label="Response table"><table>{children}</table></div>;
  },
};

export function MarkdownResponse({ text }: { text: string }) {
  return <div className="response-markdown"><Markdown remarkPlugins={[remarkGfm]} components={components}>{text}</Markdown></div>;
}

export function ChatResponseContent({ text, copyable = true }: { text: string | null | undefined; copyable?: boolean }) {
  const structured = structuredResponse(text, false);
  return <div className="response-content">
    {structured ? <DataInspector value={structured} /> : text ? <MarkdownResponse text={text} /> : <TextContent text={text} />}
    {text && copyable && <CopyResponseButton text={text} />}
  </div>;
}
