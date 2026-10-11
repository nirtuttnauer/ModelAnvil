"""Build a bounded reproducible plain-text corpus from a pinned repository revision."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', default='HEAD')
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=root)
    commit = git('rev-parse', '--verify', '--end-of-options', args.revision + '^{commit}').decode().strip()
    if not re.fullmatch('[a-f0-9]{40}', commit):
        parser.error('Resolve a repository commit before building the corpus.')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(args.model_dir), local_files_only=True, trust_remote_code=False)
    names = git('ls-tree', '-r', '--name-only', commit, 'docs/engineering').decode().splitlines()
    rows, sources, seen_content = [], [], set()
    for name in sorted(n for n in names if n.endswith('.md') and '/verification/' not in n)[:24]:
        raw = git('show', commit + ':' + name)
        if len(raw) > 256 * 1024:
            raise ValueError('Documentation source exceeds its corpus size limit.')
        paragraphs = re.split(r'\n\s*\n', raw.decode())
        paragraph = next((p for p in paragraphs if p[:1].isalpha() and len(p.split()) >= 12), None)
        if paragraph is None:
            continue
        words = paragraph.split()[:64]
        while len(tokenizer.encode(' '.join(words), add_special_tokens=True)) > 128:
            words.pop()
        text = ' '.join(words)
        content_sha = hashlib.sha256(text.encode()).hexdigest()
        if content_sha in seen_content:
            continue
        seen_content.add(content_sha)
        rows.append({'schema_version': '1.0', 'sample_id': str(uuid.uuid5(uuid.NAMESPACE_URL, commit + ':' + name + ':' + content_sha)),
            'source_group_id': name, 'blocks': [{'block_id': 'documentation', 'type': 'text', 'text': text}],
            'provenance': {'source_snapshot_ref': 'git:' + commit, 'source_record_key': name + '#first-prose-paragraph-64-word-window', 'content_sha256': content_sha}})
        sources.append({'path': name, 'file_sha256': hashlib.sha256(raw).hexdigest(), 'sample_sha256': content_sha})
    if len(rows) < 6:
        raise ValueError('Select a revision containing at least six prose documentation source files.')
    with args.output.open('x') as target:
        target.write(''.join(json.dumps(r) + '\n' for r in rows))
    metadata = {'repository_commit': commit, 'sources': sources, 'rows': len(rows), 'window': 'At most 64 words of the first prose paragraph per file; explicitly bounded to 128 tokenizer tokens.',
                'grouping': 'Exact duplicate text removed before file-group-protected publication.', 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}
    args.output.with_suffix('.metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps({'commit': commit, 'rows': len(rows), 'sha256': metadata['sha256']}))


if __name__ == '__main__':
    main()
