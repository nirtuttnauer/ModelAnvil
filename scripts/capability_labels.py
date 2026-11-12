"""Render and check the README capability Evidence column from the capability manifest (stdlib only).

docs/engineering/supported-capabilities.json is canonical for capability levels and their evidence.
Each README capability row needs one manifest entry. A level above Simulation needs at least one
evidence file, and every evidence file must exist and match its recorded sha256.

    python scripts/capability_labels.py --check-readme
    python scripts/capability_labels.py --write-readme
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/engineering/supported-capabilities.json'
README = ROOT / 'README.md'
START = '<!-- capability-evidence:start -->'
END = '<!-- capability-evidence:end -->'
HEADING = '## Current capabilities'
COLUMNS = ['Area', 'Implemented scope', 'Guide']
# Same codes and names as modelanvil.runners.evidence.LEVELS and the browser labels.
LEVELS = {
    'configuration_only': 'Configuration only',
    'simulation': 'Simulation',
    'integrated_execution': 'Integrated execution',
    'hardware_qualified': 'Hardware qualified',
    'unknown': 'Unknown evidence',
}
NEEDS_EVIDENCE = {'integrated_execution', 'hardware_qualified'}
DIGEST = re.compile('[0-9a-f]{64}')
NOTE = ('Each Evidence cell is generated from [supported-capabilities.json](docs/engineering/supported-capabilities.json), '
        'which pins every linked record by SHA-256. `python scripts/capability_labels.py --check-readme` fails when a row, '
        'level, record or cell disagrees.')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_manifest(path=MANIFEST):
    return json.loads(Path(path).read_text())


def evidence_problems(owner, entry, root):
    """Problems with one manifest entry's level and evidence files."""
    level, evidence = entry.get('level'), entry.get('evidence')
    if level not in LEVELS:
        return [f'{owner}: level {level!r} is not one of {", ".join(LEVELS)}.']
    if not isinstance(evidence, list):
        return [f'{owner}: evidence must be a list.']
    problems = []
    if level in NEEDS_EVIDENCE and not evidence:
        problems.append(f'{owner}: {LEVELS[level]} needs at least one evidence file.')
    base = (root / MANIFEST.relative_to(ROOT)).parent
    for item in evidence:
        path, recorded = (item.get('path'), item.get('sha256')) if isinstance(item, dict) else (None, None)
        if not isinstance(path, str) or not path or not isinstance(recorded, str) or not DIGEST.fullmatch(recorded):
            problems.append(f'{owner}: evidence entries need a path and a 64-character lowercase sha256: {item!r}.')
            continue
        target = (base / path).resolve()
        if not target.is_relative_to(root.resolve()):
            problems.append(f'{owner}: evidence {path} is outside the repository.')
        elif not target.is_file():
            problems.append(f'{owner}: evidence {path} does not exist.')
        else:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if actual != recorded:
                problems.append(f'{owner}: evidence {path} has sha256 {actual}; the manifest records {recorded}.')
    return problems


def manifest_problems(manifest, root=ROOT):
    problems = []
    for index, operation in enumerate(manifest.get('operations', [])):
        problems += evidence_problems(f'operations[{index}] {operation.get("operation")}', operation, root)
    rows = manifest.get('readme_rows')
    if not isinstance(rows, list) or not rows:
        return problems + ['The manifest has no readme_rows.']
    areas = [row.get('area') for row in rows]
    if not all(isinstance(area, str) and area for area in areas):
        problems.append('Every manifest row needs a non-empty area that matches its README row.')
    for area in sorted({a for a in areas if areas.count(a) > 1}, key=str):
        problems.append(f'Manifest row {area!r} appears more than once.')
    for row in rows:
        problems += evidence_problems(f'Manifest row {row.get("area")!r}', row, root)
    return problems


def table_bounds(text):
    """Start and end offsets of the capability table, with or without the generated markers."""
    if START in text:
        require(text.count(START) == 1 and END in text and text.index(START) < text.index(END),
                'README capability markers are missing or out of order.')
        return text.index(START), text.index(END) + len(END)
    require(HEADING in text, f'README has no {HEADING!r} section.')
    lines = text[text.index(HEADING):].splitlines(keepends=True)
    offset = text.index(HEADING)
    begin = None
    for line in lines:
        if line.startswith('|') and begin is None:
            begin = offset
        elif begin is not None and not line.startswith('|'):
            return begin, offset
        offset += len(line)
    require(begin is not None, 'README capability table is missing.')
    return begin, offset


def split_row(line):
    line = line.strip()
    require(line.startswith('|') and line.endswith('|'), f'Not a table row: {line!r}.')
    return [cell.strip() for cell in line[1:-1].split('|')]


def readme_rows(text):
    """README capability rows as lists of cells, header and separator excluded."""
    begin, end = table_bounds(text)
    lines = [line for line in text[begin:end].splitlines() if line.startswith('|')]
    require(len(lines) >= 3, 'README capability table has no rows.')
    header = split_row(lines[0])
    require(header in (COLUMNS, COLUMNS + ['Evidence']), f'Unexpected README capability columns: {header}.')
    rows = [split_row(line) for line in lines[2:]]
    for row in rows:
        require(len(row) == len(header), f'README row {row[0]!r} has {len(row)} cells; expected {len(header)}.')
    areas = [row[0] for row in rows]
    require(len(set(areas)) == len(areas), 'README capability areas must be unique.')
    return rows


def evidence_cell(row, root=ROOT):
    base = (root / MANIFEST.relative_to(ROOT)).parent
    links = [f'[{number}]({(base / item["path"]).resolve().relative_to(root.resolve()).as_posix()})'
             for number, item in enumerate(row['evidence'], 1)]
    return LEVELS[row['level']] + (': ' + ', '.join(links) if links else '')


def render(text, manifest, root=ROOT):
    """README text with a regenerated capability table. Raises when the manifest and README disagree."""
    problems = manifest_problems(manifest, root)
    require(not problems, '\n'.join(problems))
    by_area = {row['area']: row for row in manifest['readme_rows']}
    rows = readme_rows(text)
    areas = [row[0] for row in rows]
    missing = [area for area in areas if area not in by_area]
    extra = [area for area in by_area if area not in areas]
    require(not missing and not extra, '\n'.join(
        [f'README row {area!r} is missing from the manifest.' for area in missing]
        + [f'Manifest row {area!r} is not in the README table.' for area in extra]))
    lines = [START, '| ' + ' | '.join(COLUMNS + ['Evidence']) + ' |', '| --- | --- | --- | --- |']
    lines += ['| ' + ' | '.join(row[:3] + [evidence_cell(by_area[row[0]], root)]) + ' |' for row in rows]
    lines += ['', NOTE, END]
    begin, end = table_bounds(text)
    rest = text[end:]
    if START not in text:
        rest = '\n' + rest
    return text[:begin] + '\n'.join(lines) + rest


def check(text, manifest, root=ROOT):
    require(START in text, 'README capability Evidence column is not generated; run --write-readme.')
    require(render(text, manifest, root) == text,
            'README Evidence column differs from the manifest; run python scripts/capability_labels.py --write-readme.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--write-readme', action='store_true')
    group.add_argument('--check-readme', action='store_true')
    args = parser.parse_args()
    text, manifest = README.read_text(), load_manifest()
    try:
        if args.write_readme:
            README.write_text(render(text, manifest))
        else:
            check(text, manifest)
    except ValueError as exc:
        raise SystemExit(str(exc))


if __name__ == '__main__':
    main()
