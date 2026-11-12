#!/usr/bin/env python3
"""Build the ANVIL-008 SPDX table from saved pip-licenses and license-checker output.

Input is the raw JSON this inventory already saves: one ``<group>.all.json`` per
root ``requirements*.txt`` file (``pip-licenses --from=all --format=json
--with-urls --order=name`` in a clean venv) and, optionally, one
``license-checker --production --json`` file for ``web/package-lock.json``.
The script makes no network calls and installs nothing.

SPDX rules, in order:

1. ``License-Expression`` when pip-licenses reports one.
2. A row in ``LICENSE_FILE_ROWS``: the SPDX was read from the package's own
   license file or license text, and the row says which file.
3. ``License-Metadata`` when it is one unambiguous token in ``METADATA_SPDX``.
4. ``License-Classifier`` when it is one unambiguous classifier in
   ``CLASSIFIER_SPDX``.
5. Otherwise ``UNKNOWN``.

A package is ``direct`` when its name is on a line of the group's requirements
file, following ``-r`` includes, and ``transitive`` otherwise. A direct name that
is not installed gets a ``not-installed`` row, so a host whose environment
markers exclude a requirement shows it instead of dropping it.

pip-licenses leaves out ``pip``, ``setuptools``, ``wheel``, ``prettytable`` and
``wcwidth`` unless ``--with-system`` is set. When ``<group>.system.json`` exists
(the same command with ``--with-system --packages <names>``), its rows other
than ``pip`` are merged in and their source says so. An npm package is ``direct``
when ``web/package.json`` lists it under ``dependencies``.

``--check-venvs DIR`` reopens each ``LICENSE_FILE_ROWS`` file in
``DIR/<group>/lib/python*/site-packages`` and fails if the quoted text is not
there. With ``--notices FILE`` it also lists GPL-family declarations in the
license files that the installed wheels ship for bundled components. This is an
inventory tool, not legal advice.
"""
import argparse
import csv
import glob
import io
import json
from pathlib import Path
import re
import sys


GROUP_ORDER = [
    'requirements.txt', 'requirements.production.txt', 'requirements.documents.txt',
    'requirements.gpu.txt', 'requirements.inference.txt', 'requirements.embeddings.txt',
    'requirements.audio.txt', 'requirements.vision.txt', 'requirements.tools.txt',
    'requirements.selfhost.lock.txt', 'requirements.specialists.txt',
]
WEB_GROUP = 'web/package-lock.json'

METADATA_SPDX = {
    'MIT': 'MIT', 'MIT License': 'MIT',
    'BSD-3-Clause': 'BSD-3-Clause', 'BSD 3-Clause License': 'BSD-3-Clause', '3-Clause BSD License': 'BSD-3-Clause',
    'Apache-2.0': 'Apache-2.0', 'Apache 2.0': 'Apache-2.0', 'Apache 2.0 License': 'Apache-2.0',
    'Apache License 2.0': 'Apache-2.0', 'Apache License, Version 2.0': 'Apache-2.0',
    'MPL-2.0': 'MPL-2.0', 'MPL-2.0 AND MIT': 'MPL-2.0 AND MIT',
    'ISC License': 'ISC', 'ISC': 'ISC',
    'LicenseRef-NVIDIA-Proprietary': 'LicenseRef-NVIDIA-Proprietary',
    'NVIDIA Proprietary Software': 'LicenseRef-NVIDIA-Proprietary',
}
CLASSIFIER_SPDX = {
    'MIT License': 'MIT',
    'Apache Software License': 'Apache-2.0',
    'ISC License (ISCL)': 'ISC',
    'Mozilla Public License 2.0 (MPL 2.0)': 'MPL-2.0',
}

# Rows whose SPDX was read from the package's own license file or license text.
# (name, version) -> (spdx, source, evidence, check). ``check`` is a site-packages
# glob and a string it must contain, or None when the file is not in the wheel.
LICENSE_FILE_ROWS = {
    ('django-filter', '25.2'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'django_filter-25.2.dist-info/LICENSE lines 4-13: the 3-clause BSD text '
        '(clause 3 is worded "The names of its contributors may not be used to endorse")',
        ('django_filter-25.2.dist-info/LICENSE', 'may not be used to endorse or promote products')),
    ('python-dateutil', '2.9.0.post0'): (
        'Apache-2.0 AND BSD-3-Clause', 'license file in the installed wheel',
        'python_dateutil-2.9.0.post0.dist-info/LICENSE line 4 (Apache License, Version 2.0) and '
        'line 54 ("The above BSD License Applies to all code, even that also covered by Apache 2.0.")',
        ('python_dateutil-2.9.0.post0.dist-info/LICENSE', 'The above BSD License Applies to all code')),
    ('sqlparse', '0.6.0'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'sqlparse-0.6.0.dist-info/licenses/LICENSE line 12: 3-clause BSD non-endorsement clause',
        ('sqlparse-0.6.0.dist-info/licenses/LICENSE', 'Neither the name of the authors')),
    ('sqlparse', '0.6.1'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'sqlparse-0.6.1.dist-info/licenses/LICENSE line 12: 3-clause BSD non-endorsement clause',
        ('sqlparse-0.6.1.dist-info/licenses/LICENSE', 'Neither the name of the authors')),
    ('Jinja2', '3.1.6'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'jinja2-3.1.6.dist-info/licenses/LICENSE.txt line 14: 3-clause BSD non-endorsement clause',
        ('jinja2-3.1.6.dist-info/licenses/LICENSE.txt', 'Neither the name of the copyright holder')),
    ('mpmath', '1.3.0'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'mpmath-1.3.0.dist-info/LICENSE line 13: 3-clause BSD non-endorsement clause',
        ('mpmath-1.3.0.dist-info/LICENSE', 'Neither the name of the copyright holder')),
    ('sympy', '1.14.0'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'sympy-1.14.0.dist-info/licenses/LICENSE line 13: 3-clause BSD non-endorsement clause',
        ('sympy-1.14.0.dist-info/licenses/LICENSE', 'Neither the name of SymPy')),
    ('torchvision', '0.28.0'): (
        'BSD-3-Clause', 'license file in the installed wheel',
        'torchvision-0.28.0.dist-info/LICENSE line 16: 3-clause BSD non-endorsement clause',
        ('torchvision-0.28.0.dist-info/LICENSE', 'Neither the name of the copyright holder')),
    ('nvidia-nvtx', '13.0.85'): (
        'Apache-2.0', 'license file in the installed wheel',
        'Linux only: the license file in the nvidia-nvtx 13.0.85 wheel is the Apache License 2.0 (11 November run)', None),
    ('numpy', '2.3.3'): (
        'BSD-3-Clause', 'license text in metadata',
        'numpy-2.3.3.dist-info/LICENSE.txt line 16: 3-clause BSD non-endorsement clause; later sections '
        'list bundled components (see bundled notices)',
        ('numpy-2.3.3.dist-info/LICENSE.txt', 'Neither the name of the NumPy Developers')),
    ('scipy', '1.18.1'): (
        'BSD-3-Clause', 'license text in metadata',
        'scipy-1.18.1.dist-info/LICENSE.txt line 16: 3-clause BSD non-endorsement clause; later sections '
        'list bundled components (see bundled notices)',
        ('scipy-1.18.1.dist-info/LICENSE.txt', 'Neither the name of the copyright holder')),
    ('sentencepiece', '0.2.1'): (
        'Apache-2.0', 'LICENSE in the sentencepiece-0.2.1 sdist',
        'sentencepiece-0.2.1.tar.gz: sentencepiece-0.2.1/sentencepiece/LICENSE lines 2-3 '
        '"Apache License" / "Version 2.0, January 2004"; the wheel has no license file', None),
    ('pypdfium2', '5.14.0'): (
        'Apache-2.0 OR BSD-3-Clause', 'SPDX header in the installed wheel and README Licensing section',
        'pypdfium2/__init__.py line 2 "SPDX-License-Identifier: Apache-2.0 OR BSD-3-Clause" (43 of the 45 .py files); '
        'README Licensing section, line 862 of the wheel METADATA; the bundled PDFium binary ships its own '
        'notices under BUILD_LICENSES',
        ('pypdfium2/__init__.py', 'SPDX-License-Identifier: Apache-2.0 OR BSD-3-Clause')),
}

NAME = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._-]*)')


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def direct_names(path, seen=None):
    """Names on the lines of a requirements file, following -r includes."""
    seen = set() if seen is None else seen
    names = set()
    if path in seen:
        return names
    seen.add(path)
    for raw in path.read_text().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith(('-r ', '--requirement ')):
            names |= direct_names(path.parent / line.split(None, 1)[1].strip(), seen)
            continue
        if line.startswith('-'):
            continue
        match = NAME.match(line)
        if match:
            names.add(canonical(match.group(1)))
    return names


def kind_of(spdx):
    upper = spdx.upper()
    if upper in ('UNKNOWN', 'NOT-INSTALLED'):
        return 'unknown'
    tokens = re.split(r'[\s()]+', upper)
    for prefix, label in (('AGPL', 'AGPL'), ('LGPL', 'LGPL'), ('GPL', 'GPL'), ('MPL', 'MPL')):
        if any(token.startswith(prefix) for token in tokens):
            return label
    return ''


def resolve(entry):
    name, version = entry['Name'], entry['Version']
    expression = entry.get('License-Expression', 'UNKNOWN')
    if expression and expression != 'UNKNOWN':
        return expression, 'License-Expression'
    if (name, version) in LICENSE_FILE_ROWS:
        spdx, source, _evidence, _check = LICENSE_FILE_ROWS[(name, version)]
        return spdx, source
    metadata = (entry.get('License-Metadata') or 'UNKNOWN').strip()
    if metadata in METADATA_SPDX:
        return METADATA_SPDX[metadata], 'License-Metadata'
    classifier = (entry.get('License-Classifier') or 'UNKNOWN').strip()
    if classifier in CLASSIFIER_SPDX:
        return CLASSIFIER_SPDX[classifier], 'License-Classifier'
    return 'UNKNOWN', 'no SPDX expression or license file in the installed wheel'


def python_rows(licenses_dir, root):
    files = {path.name for path in root.glob('requirements*.txt')}
    order = [name for name in GROUP_ORDER if name in files] + sorted(files - set(GROUP_ORDER))
    rows, missing = [], []
    for group in order:
        report = licenses_dir / (group[:-len('.txt')] + '.all.json')
        if not report.is_file():
            missing.append(group)
            continue
        direct = direct_names(root / group)
        entries = json.loads(report.read_text())
        system = report.with_name(report.name.replace('.all.json', '.system.json'))
        system_names = set()
        if system.is_file():
            extra = [entry for entry in json.loads(system.read_text()) if canonical(entry['Name']) != 'pip']
            system_names = {canonical(entry['Name']) for entry in extra}
            entries = sorted(entries + extra, key=lambda entry: entry['Name'])
        installed = set()
        for entry in entries:
            installed.add(canonical(entry['Name']))
            spdx, source = resolve(entry)
            if canonical(entry['Name']) in system_names:
                source += ' (--with-system run)'
            relation = 'direct' if canonical(entry['Name']) in direct else 'transitive'
            rows.append([group, entry['Name'], entry['Version'], relation, spdx, source, kind_of(spdx)])
        for name in sorted(direct - installed):
            rows.append([group, name, '', 'not-installed', 'NOT-INSTALLED',
                         'named in the requirements file, not installed on this host', 'unknown'])
    return rows, missing


def web_rows(path, package_json):
    direct = set(json.loads(package_json.read_text()).get('dependencies', {}))
    rows = []
    for key, entry in json.loads(path.read_text()).items():
        if entry.get('private'):
            continue  # The application itself (modelanvil-web), not a dependency.
        name, _, version = key.rpartition('@')
        licenses = entry.get('licenses', 'UNKNOWN')
        spdx = ' OR '.join(licenses) if isinstance(licenses, list) else licenses
        relation = 'direct' if name in direct else 'transitive'
        rows.append([WEB_GROUP, name, version, relation, spdx, 'license-checker --production', kind_of(spdx)])
    return rows


def check_license_files(rows, venvs):
    failures = []
    for group, name, version, *_ in rows:
        item = LICENSE_FILE_ROWS.get((name, version))
        if group == WEB_GROUP or not item or not item[3]:
            continue
        pattern, needle = item[3]
        venv = venvs / group[:-len('.txt')]
        hits = glob.glob(str(venv / 'lib' / 'python*' / 'site-packages' / pattern))
        found = any(needle in Path(hit).read_text(errors='replace') for hit in hits)
        print(f"{'ok' if found else 'FAIL'}  {group}  {name} {version}  {pattern}")
        if not found:
            failures.append((group, name, version))
    return failures


NOTICE_SKIP = {'METADATA', 'RECORD', 'WHEEL', 'INSTALLER', 'REQUESTED', 'entry_points.txt',
               'top_level.txt', 'direct_url.json'}
DECLARATION = re.compile(r'^\s*(?:License|SPDX-License-Identifier)\s*[:=]\s*"?(.*\bA?L?GPL.*?)"?\s*$')
GNU_TITLE = re.compile(r'GNU (?:LESSER |LIBRARY |AFFERO )?GENERAL PUBLIC LICENSE', re.IGNORECASE)
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def scan_notices(venvs, groups):
    """GPL-family declarations in the license files that installed wheels ship.

    Reads every file in each ``*.dist-info`` except packaging metadata. A hit is a
    ``License:`` or ``SPDX-License-Identifier`` line naming GPL, LGPL or AGPL, or
    a file that opens with a GNU license title. These are notices for components
    bundled inside a wheel; they are not the package's own SPDX expression.
    """
    hits = []
    for group in groups:
        site = glob.glob(str(venvs / group[:-len('.txt')] / 'lib' / 'python*' / 'site-packages'))
        for dist_info in sorted(Path(site[0]).glob('*.dist-info')) if site else []:
            dist, _, version = dist_info.name[:-len('.dist-info')].partition('-')
            for path in sorted(p for p in dist_info.rglob('*') if p.is_file() and p.name not in NOTICE_SKIP):
                lines = path.read_text(errors='replace').splitlines()
                head = ' '.join(line.strip() for line in lines[:8])
                title = GNU_TITLE.search(head)
                if title:
                    hits.append((group, dist, version, str(path.relative_to(dist_info)), 1, 'file opens with ' + title.group(0)))
                for number, line in enumerate(lines, 1):
                    match = DECLARATION.match(line)
                    if match:
                        hits.append((group, dist, version, str(path.relative_to(dist_info)), number,
                                     EMAIL.sub('[redacted]', match.group(1).strip())[:160]))
    return hits


def markdown(rows, title, intro):
    out = io.StringIO()
    out.write(f'# {title}\n\n{intro}\n\n')
    out.write('| Group | Name | Version | Relation | SPDX | Source |\n| --- | --- | --- | --- | --- | --- |\n')
    for group, name, version, relation, spdx, source, _kind in rows:
        out.write(f'| {group} | {name} | {version} | {relation} | {spdx} | {source} |\n')
    used = sorted({(row[1], row[2]) for row in rows if (row[1], row[2]) in LICENSE_FILE_ROWS})
    if used:
        out.write('\n## Rows read from a license file\n\n| Name | Version | SPDX | Evidence |\n| --- | --- | --- | --- |\n')
        for key in used:
            spdx, _source, evidence, _check = LICENSE_FILE_ROWS[key]
            out.write(f'| {key[0]} | {key[1]} | {spdx} | {evidence} |\n')
    return out.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n', 1)[0])
    parser.add_argument('--licenses', type=Path, required=True, help='directory of <group>.all.json files')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='repo root')
    parser.add_argument('--web', type=Path, help='license-checker --production --json output')
    parser.add_argument('--web-package', type=Path, help='web/package.json that names the direct npm dependencies')
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--md', type=Path, required=True)
    parser.add_argument('--title', default='SPDX table')
    parser.add_argument('--intro', default='')
    parser.add_argument('--check-venvs', type=Path, help='directory of the per-group venvs that produced --licenses')
    parser.add_argument('--notices', type=Path, help='with --check-venvs: write GPL-family bundled notices here (TSV)')
    args = parser.parse_args()

    rows, missing = python_rows(args.licenses, args.root)
    if missing:
        sys.exit(f'missing pip-licenses output for: {", ".join(missing)}')
    if args.web:
        rows += web_rows(args.web, args.web_package or args.root / 'web' / 'package.json')
    if args.check_venvs and check_license_files(rows, args.check_venvs):
        sys.exit('a license-file row did not match the installed file')

    with args.csv.open('w', newline='') as handle:
        writer = csv.writer(handle, lineterminator='\n')
        writer.writerow(['group', 'name', 'version', 'relation', 'spdx', 'source', 'kind'])
        writer.writerows(rows)
    args.md.write_text(markdown(rows, args.title, args.intro))
    if args.check_venvs and args.notices:
        groups = list(dict.fromkeys(row[0] for row in rows if row[0] != WEB_GROUP))
        with args.notices.open('w', newline='') as handle:
            writer = csv.writer(handle, delimiter='\t', lineterminator='\n')
            writer.writerow(['group', 'distribution', 'version', 'file', 'line', 'declaration'])
            writer.writerows(scan_notices(args.check_venvs, groups))

    counts = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    for group, count in counts.items():
        print(f'{count:5d}  {group}')
    print(f'{len(rows):5d}  total')
    for row in rows:
        if row[6]:
            print(f'{row[6]:8s} {row[0]}  {row[1]} {row[2]}  {row[4]}')


if __name__ == '__main__':
    main()
