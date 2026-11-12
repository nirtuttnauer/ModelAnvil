"""ANVIL-020 expanded SciFact small correctness check (policy rag-expanded-corpus-v1).

The full pinned SciFact corpus runs as five production-limit shards. The BEIR
SciFact test claims are held out; group-disjoint training claims are the
development split. The development run writes thresholds that a commit freezes
before the held-out run. Run time never downloads; `cache_beir_qrels` is the
only explicit bootstrap this module adds.
"""
import hashlib
import json
import platform
import re
import subprocess
import tarfile
import time
from pathlib import Path

from modelanvil.rag.benchmark_corpus import PINS as ARCHIVE_PINS, cache_directory, ordered_key

ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / 'scripts' / 'rag-expanded-corpus-policy.json'
PINS_PATH = Path(__file__).with_name('benchmark-expanded-pins.json')
EVIDENCE = ROOT / 'docs' / 'engineering' / 'verification' / 'anvil-020-2026-11-12'
PLAN_PATH = EVIDENCE / 'frozen-plan.json'
ROLES = ('development', 'held_out')
MODES = ('real', 'random', 'full_text')
BASELINES = {'random': 'random-vector baseline', 'full_text': 'SQL full-text baseline'}
LABEL = 'small correctness check'
QRELS_HEADER = 'query-id\tcorpus-id\tscore\r\n'
# Production limits from modelanvil/rag/ingestion.py index_documents; not changed here.
MAX_SOURCE_BYTES = 2000000
MAX_CHUNKS = 10000
TITLE_FIELD_LIMIT = 255  # SourceDocument.title max_length
BEIR_FILE = 'beir-scifact-test-qrels.tsv'


def policy():
    return json.loads(POLICY_PATH.read_text())


def pins():
    return json.loads(PINS_PATH.read_text())


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def dumps(value):
    """Indented JSON; 64-hex digests are stored as JSON unicode escapes so stock gitleaks skips them."""
    text = json.dumps(value, indent=2, allow_nan=False)
    return re.sub(r'"([0-9a-f]{64})"', lambda m: '"' + ''.join('\\u%04x' % ord(c) for c in m.group(1)) + '"', text) + '\n'


def content(document):
    return document['title'] + '\n' + ' '.join(document['abstract'])


def source_record(key, document):
    """The indexed content keeps the full title; only the 255-character title field is shortened."""
    return {'title': document['title'][:TITLE_FIELD_LIMIT], 'source_uri': 'scifact:' + key, 'content': content(document)}


def normalized(text):
    return ' '.join(text.casefold().split())


def judged(claim):
    """BEIR relevance: cited documents, deduplicated in file order, grade 1."""
    result = []
    for value in claim['cited_doc_ids']:
        if str(value) not in result:
            result.append(str(value))
    return result


def qrels_tsv(claims):
    """The BEIR qrels layout: header, one CRLF row per judged document, in claim file order."""
    return (QRELS_HEADER + ''.join(f"{claim['id']}\t{doc}\t1\r\n" for claim in claims for doc in judged(claim))).encode()


def load_members():
    """Verify the unchanged publisher archive, then every member the expanded pins name."""
    root = cache_directory()
    manifest = pins()
    if manifest['archive']['sha256'] != ARCHIVE_PINS['sha256']:
        raise ValueError('The expanded pins name a different publisher archive.')
    for name, expected in [('scifact.tar.gz', ARCHIVE_PINS['sha256']), ('LICENSE-upstream.md', ARCHIVE_PINS['license_sha256'])]:
        path = root / name
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise ValueError('Bootstrap the pinned public retrieval benchmark cache first.')
    wanted = {'corpus': manifest['corpus'], **{pin['role']: {**pin, 'member': name} for name, pin in manifest['claims'].items()}}
    rows = {}
    with tarfile.open(root / 'scifact.tar.gz', 'r:gz') as archive:
        for role, pin in wanted.items():
            member = archive.getmember(pin['member'])
            if not member.isfile() or member.size != pin['byte_size']:
                raise ValueError('An archive member differs from its expanded pin.')
            data = archive.extractfile(member).read()
            if sha256(data) != pin['sha256']:
                raise ValueError('An archive member checksum differs from its expanded pin.')
            parsed = [json.loads(line) for line in data.splitlines()]
            if len(parsed) != pin['records']:
                raise ValueError('An archive member record count differs from its expanded pin.')
            rows[role] = parsed
    return rows['corpus'], rows['development'], rows['held_out']


def select(corpus, development_claims, held_out_claims):
    """Hold out every test claim; keep training claims that share no source group or text with them."""
    docs = {str(d['doc_id']): d for d in corpus}
    if len(docs) != len(corpus):
        raise ValueError('The corpus repeats a document ID.')
    parent = {key: key for key in docs}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    for claim in development_claims + held_out_claims:
        ids = sorted(set(judged(claim)) | {str(key) for key in claim['evidence']})
        if not judged(claim) or any(key not in docs for key in ids):
            raise ValueError('A claim has no judged document or names a missing one.')
        for other in ids[1:]:
            a, b = find(ids[0]), find(other)
            parent[max(a, b)] = min(a, b)

    def row(claim, role):
        relevant = judged(claim)
        return {'id': str(claim['id']), 'query': claim['claim'], 'relevant': relevant,
                'source_group': find(relevant[0]), 'role': role}

    held = [row(claim, 'held_out') for claim in held_out_claims]
    groups = {r['source_group'] for r in held}
    texts = {normalized(r['query']) for r in held}
    development = [r for r in (row(claim, 'development') for claim in development_claims)
                   if r['source_group'] not in groups and normalized(r['query']) not in texts]
    ids = [r['id'] for r in development + held]
    if len(set(ids)) != len(ids):
        raise ValueError('A claim ID repeats or crosses the evaluation split.')
    for rows in (development, held):
        rows.sort(key=lambda r: ordered_key('query', r['id']))
    return docs, development + held


def shard_of(doc_id, count):
    return int(ordered_key('shard', doc_id)[:8], 16) % count


def shard_plan(docs, count):
    from modelanvil.rag.chunking import token_chunks
    current = policy()['retrieval']
    shards = [[] for _ in range(count)]
    for key in sorted(docs, key=int):
        shards[shard_of(key, count)].append(key)
    result = []
    for index, ids in enumerate(shards):
        size = sum(len(content(docs[key]).encode()) for key in ids)
        chunks = sum(1 for key in ids for _ in token_chunks(content(docs[key]), current['chunk_size'], current['chunk_overlap']))
        if not ids or size > MAX_SOURCE_BYTES or chunks > MAX_CHUNKS:
            raise ValueError('A shard exceeds the production local index limits.')
        result.append({'shard': index, 'documents': len(ids), 'source_text_bytes': size, 'token_chunks': chunks, 'document_ids': ids})
    return result


def build_plan(members=None):
    """Rebuild the frozen split, judgments and shards from the pinned members; no model or metric."""
    corpus, development_claims, held_out_claims = members or load_members()
    current, manifest = policy(), pins()
    docs, queries = select(corpus, development_claims, held_out_claims)
    chosen = {q['id'] for q in queries if q['role'] == 'development'}
    qrels = {'development': qrels_tsv([c for c in development_claims if str(c['id']) in chosen]),
             'held_out': qrels_tsv(held_out_claims)}
    for role, data in qrels.items():
        pin = manifest['qrels'][role]
        if sha256(data) != pin['sha256'] or len(data) != pin['byte_size']:
            raise ValueError(f'Rebuilt {role} judgments differ from their pin.')
    size = current['size']
    counts = {role: [q for q in queries if q['role'] == role] for role in ROLES}
    observed = {'documents': len(docs),
                'development_queries': len(counts['development']), 'held_out_queries': len(counts['held_out']),
                'development_judgments': sum(len(q['relevant']) for q in counts['development']),
                'held_out_judgments': sum(len(q['relevant']) for q in counts['held_out']),
                'development_judged_documents': len({d for q in counts['development'] for d in q['relevant']}),
                'held_out_judged_documents': len({d for q in counts['held_out'] for d in q['relevant']})}
    if any(size[key] != value for key, value in observed.items()):
        raise ValueError('The rebuilt split differs from the policy size.')
    shards = shard_plan(docs, current['index']['shards'])
    if sum(s['token_chunks'] for s in shards) != size['token_chunks_expected']:
        raise ValueError('The token chunk count differs from the policy size.')
    plan = {'schema': 'modelanvil.retrieval-expanded-plan.v1', 'label': LABEL, 'policy_id': current['id'],
            'policy_sha256': sha256(POLICY_PATH.read_bytes()), 'pins_sha256': sha256(PINS_PATH.read_bytes()),
            'archive_sha256': ARCHIVE_PINS['sha256'], 'qrels_sha256': {role: sha256(data) for role, data in qrels.items()},
            'size': observed, 'shards': shards,
            'queries': [{k: v for k, v in q.items() if k != 'query'} for q in queries]}
    return plan, docs, queries


def cache_beir_qrels():
    """Explicit operator bootstrap of the BEIR SciFact test qrels for the one-time cross-check."""
    from urllib.request import build_opener, HTTPRedirectHandler, Request

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    pin = pins()['qrels']['held_out']['beir_cross_check']
    root = cache_directory()
    root.mkdir(parents=True, exist_ok=True)
    target = root / BEIR_FILE
    if target.exists():
        if sha256(target.read_bytes()) != pin['sha256']:
            raise ValueError('Cached BEIR qrels differ from the pin; preserve them and use a fresh cache directory.')
        return target
    with build_opener(NoRedirect()).open(Request(pin['url'], headers={'User-Agent': 'ModelAnvil-public-qualification/1'}), timeout=30) as response:
        data = response.read(pin['byte_size'] + 1)
    if len(data) != pin['byte_size'] or sha256(data) != pin['sha256']:
        raise ValueError('BEIR qrels download differs from the pin.')
    with target.open('xb') as stream:
        stream.write(data)
    return target


def beir_cross_check():
    """The cached BEIR file and the judgments rebuilt from the publisher claims are the same bytes."""
    pin = pins()['qrels']['held_out']
    path = cache_directory() / BEIR_FILE
    if not path.is_file():
        raise ValueError('Bootstrap the BEIR qrels with cache_beir_qrels() first.')
    beir = path.read_bytes()
    rebuilt = qrels_tsv(load_members()[2])
    return {'beir_file_sha256': sha256(beir), 'rebuilt_sha256': sha256(rebuilt), 'identical_bytes': beir == rebuilt,
            'pinned_sha256': pin['sha256'], 'matches_pin': sha256(beir) == pin['sha256'] == sha256(rebuilt)}


def committed(path, root=ROOT):
    """Return the commit that last changed a tracked file that is unchanged from HEAD; refuse otherwise."""
    path, root = Path(path).resolve(), Path(root).resolve()
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        raise ValueError(f'{path} is outside the repository; frozen inputs must be committed there.') from None

    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    if git('ls-files', '--error-unmatch', '--', relative).returncode != 0:
        raise ValueError(f'{relative} is not committed; commit it before this run.')
    if git('diff', '--quiet', 'HEAD', '--', relative).returncode != 0:
        raise ValueError(f'{relative} differs from HEAD; commit it before this run.')
    result = git('log', '-1', '--format=%H', '--', relative)
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(f'No commit records {relative}.')
    return result.stdout.strip()


def merged(per_shard, limit):
    """Merge per-shard candidates by score, then chunk_id: one index over all chunks, apart from exact ties."""
    return sorted((row for rows in per_shard for row in rows), key=lambda row: (-row.score, row.chunk_id))[:limit]


def documents_of(ranked, cutoff):
    ids = []
    for row in ranked:
        doc = row.chunk.document.source_uri.split(':', 1)[1]
        if doc not in ids:
            ids.append(doc)
    return ids[:cutoff]


def random_vector(identity, seed):
    import numpy as np
    value = int(hashlib.sha256((str(seed) + ':' + identity).encode()).hexdigest()[:16], 16)
    vector = np.random.default_rng(value).normal(size=384).astype('float32')
    return (vector / np.linalg.norm(vector)).tolist()


def _native_index(source, project, chunks, kind, vectors, shard, current):
    from modelanvil.rag import embedding_adapter as adapter
    from modelanvil.rag.embedding_jobs import create_hnsw, runtime_digest
    from modelanvil.rag.models import ChunkEmbedding, EmbeddingSpace, IndexVersion
    real = kind == 'real'
    seed = current['retrieval']['random_seed']
    space = EmbeddingSpace.all_objects.create(tenant_id=project.tenant_id, project=project, name=f'{kind}-shard-{shard}',
        model_name=adapter.PINS['model'] if real else f'negative-control:gaussian-seed{seed}',
        model_revision=adapter.PINS['revision'] if real else digest(current), dimension=384, normalized=True,
        distance_metric='cosine', metadata={'profile_digest': digest(adapter.PINS) if real else digest(current),
            'purpose': 'public benchmark only', 'policy': current['id']})
    runtime = runtime_digest() if real else digest({'negative_control': seed, 'policy': current['id']})
    ChunkEmbedding.all_objects.bulk_create([ChunkEmbedding(tenant_id=project.tenant_id, space=space, chunk=c, vector=v,
        content_hash=c.content_hash, vector_digest=adapter.vector_digest(v), runtime_digest=runtime)
        for c, v in zip(chunks, vectors)], batch_size=1000)
    name = create_hnsw(space)
    index = IndexVersion.all_objects.create(tenant_id=project.tenant_id, project=project, knowledge_base=source.knowledge_base,
        embedding_space=space, revision_no=2 if real else 3, adapter_type='dense', status='ready', chunks_count=len(chunks),
        manifest_digest=source.manifest_digest, configuration={**source.configuration, 'embeddings_generated': True,
            'embedding_profile': {'purpose': 'real_model' if real else 'negative_control'}, 'embedding_build_runtime': runtime,
            'hnsw_index': name, 'retrieval_settings': {'dense_search': 'hnsw', 'hnsw': {'ef_search': 100}}})
    return index, name


def _aggregate(rows, cutoff):
    from modelanvil.rag.benchmark import aggregate
    result = aggregate(rows, cutoff)
    result['queries_with_returned_documents'] = sum(r['returned_documents'] > 0 for r in rows)
    return result


def run(phase, thresholds_path=None):
    """Measure one phase on actual PostgreSQL/pgvector inside a temporary owned tenant."""
    from django.db import connection
    from modelanvil.core.ids import uuid7
    from modelanvil.core.tenancy import get_active_tenant, get_active_project, set_active_tenant, set_active_project
    from modelanvil.identity.models import Tenant, Team, Project
    from modelanvil.rag import embedding_adapter as adapter
    from modelanvil.rag.ingestion import index_documents
    from modelanvil.rag.metrics import compute_all_retrieval_metrics
    from modelanvil.rag.models import (KnowledgeBase, DocumentChunk, EmbeddingSpace, ChunkEmbedding, IndexVersion,
                                       QueryTrace, RetrievalRun)
    from modelanvil.rag.retrieval import RetrievalEngine
    if phase not in ROLES:
        raise ValueError('Choose the development or held_out phase.')
    if connection.vendor != 'postgresql':
        raise ValueError('The expanded retrieval check requires actual PostgreSQL/pgvector.')
    current = policy()
    commits = {'policy': committed(POLICY_PATH), 'pins': committed(PINS_PATH), 'plan': committed(PLAN_PATH)}
    frozen = None
    if phase == 'held_out':
        if thresholds_path is None:
            raise ValueError('The held-out run needs the committed development thresholds.')
        commits['thresholds'] = committed(thresholds_path)
        frozen = json.loads(Path(thresholds_path).read_text())
    elif thresholds_path is not None:
        raise ValueError('The development run derives its thresholds; it does not read them.')
    adapter.environment()
    adapter.verified_directory()
    import torch
    torch.set_num_threads(1)
    plan, docs, queries = build_plan()
    if plan != json.loads(PLAN_PATH.read_text()):
        raise ValueError('The rebuilt plan differs from the committed frozen plan.')
    plan_digest = digest(plan)
    if frozen is not None:
        if (frozen.get('policy_id') != current['id'] or frozen.get('plan_digest') != plan_digest
                or frozen.get('source_phase') != 'development'):
            raise ValueError('The thresholds file was not frozen from this policy and plan by a development run.')
        thresholds = frozen['thresholds']
    retrieval, ann_policy = current['retrieval'], current['ann']
    candidates, cutoff, seed = retrieval['candidate_chunks'], retrieval['cutoff_documents'], retrieval['random_seed']
    primary = retrieval['primary_metric']
    rows = [q for q in queries if q['role'] == phase]
    previous = (get_active_tenant(), get_active_project())
    tenant = None
    indexes = []
    started = time.monotonic()
    timings = {}
    try:
        tenant = Tenant.objects.create(slug='retrieval-expanded-' + uuid7().hex, name='Temporary public retrieval qualification')
        set_active_tenant(tenant.pk)
        set_active_project(None)
        team = Team.all_objects.create(tenant_id=tenant.pk, name='Temporary benchmark', slug='temporary')
        project = Project.all_objects.create(tenant_id=tenant.pk, team=team, name='Temporary expanded controls', slug='controls')
        set_active_project(project.pk)
        built = []
        for shard in plan['shards']:
            base = KnowledgeBase.all_objects.create(tenant_id=tenant.pk, project=project, name=f'Pinned public SciFact shard {shard["shard"]}')
            source = index_documents(base, [source_record(key, docs[key]) for key in shard['document_ids']],
                retrieval['chunk_size'], retrieval['chunk_overlap'])
            chunks = list(DocumentChunk.all_objects.filter(tenant_id=tenant.pk, document__knowledge_base=base)
                .select_related('document').order_by('document__source_uri', 'chunk_index'))
            if len(chunks) != shard['token_chunks']:
                raise ValueError('A shard chunk count differs from the frozen plan.')
            stable = {str(c.chunk_id): c.document.source_uri.split(':', 1)[1] + ':' + str(c.chunk_index) for c in chunks}
            built.append({'shard': shard['shard'], 'source': source, 'chunks': chunks, 'stable': stable})
        timings['index_documents_seconds'] = round(time.monotonic() - started, 3)
        mark = time.monotonic()
        for item in built:
            vectors = []
            for start in range(0, len(item['chunks']), adapter.BATCH_SIZE):
                vectors.extend(adapter.encode([c.text for c in item['chunks'][start:start + adapter.BATCH_SIZE]]).tolist())
            item['vectors'] = vectors
        timings['embed_chunks_seconds'] = round(time.monotonic() - mark, 3)
        mark = time.monotonic()
        for item in built:
            item['real'], name = _native_index(item['source'], project, item['chunks'], 'real', item.pop('vectors'), item['shard'], current)
            indexes.append(name)
            item['random'], name = _native_index(item['source'], project, item['chunks'], 'random',
                [random_vector('document:' + item['stable'][str(c.chunk_id)], seed) for c in item['chunks']], item['shard'], current)
            indexes.append(name)
        timings['vector_indexes_seconds'] = round(time.monotonic() - mark, 3)
        mark = time.monotonic()
        encoded = {}
        for start in range(0, len(rows), adapter.BATCH_SIZE):
            batch = rows[start:start + adapter.BATCH_SIZE]
            encoded.update({row['id']: vector.tolist() for row, vector in zip(batch, adapter.encode([row['query'] for row in batch]))})
        controls = {row['id']: random_vector('query:' + row['id'], seed) for row in rows}
        timings['embed_queries_seconds'] = round(time.monotonic() - mark, 3)

        def relevance():
            result = {}
            for mode in MODES:
                scored = []
                for q in rows:
                    per_shard = []
                    for item in built:
                        if mode == 'full_text':
                            per_shard.append(RetrievalEngine(item['source']).retrieve_lexical(q['query'], candidates))
                        else:
                            vector = encoded[q['id']] if mode == 'real' else controls[q['id']]
                            per_shard.append(RetrievalEngine(item[mode]).retrieve_dense(vector, candidates, dense_search='exact'))
                    ranked = merged(per_shard, candidates)
                    ids = documents_of(ranked, cutoff)
                    metrics = compute_all_retrieval_metrics(ids, set(q['relevant']), {key: 1 for key in q['relevant']}, cutoff)
                    scored.append({'query_id': q['id'], 'retrieved_documents': ids, 'positive_qrels': len(q['relevant']),
                                   'candidate_chunks_returned': len(ranked), 'returned_documents': len(ids), 'metrics': metrics})
                result[mode] = _aggregate(scored, cutoff)
            return result

        def ann():
            result = []
            sample = rows[:ann_policy['queries_per_split']]
            for percent in ann_policy['filter_percent']:
                members = []
                for item in built:
                    chosen = [c for c in item['chunks'] if int(ordered_key('ann-filter', item['stable'][str(c.chunk_id)])[:8], 16) % 100 < percent]
                    if not chosen:
                        raise ValueError('A frozen ANN filter has no eligible chunks in a shard.')
                    members.append(chosen)
                originals = [dict(item['real'].configuration) for item in built]
                try:
                    for item, chosen, original in zip(built, members, originals):
                        item['real'].configuration = {**original, 'chunk_ids': [str(c.chunk_id) for c in chosen]}
                        item['real'].save(update_fields=['configuration'])
                    for ef in ann_policy['ef_search']:
                        observations = []
                        for q in sample:
                            for item in built:
                                engine = RetrievalEngine(item['real'])
                                exact = engine.retrieve_dense(encoded[q['id']], ann_policy['cutoff_chunks'], dense_search='exact')
                                actual = engine.retrieve_dense(encoded[q['id']], ann_policy['cutoff_chunks'], dense_search='hnsw',
                                                               ef_search=ef, allow_exact_fallback=False)
                                expected, found = {r.chunk_id for r in exact}, {r.chunk_id for r in actual}
                                observations.append({'query_id': q['id'], 'shard': item['shard'], 'recall': len(expected & found) / len(expected),
                                                     'exact_count': len(expected), 'ann_count': len(found),
                                                     'exact_fallback_used': engine.execution.get('exact_fallback_used')})
                        values = [o['recall'] for o in observations]
                        result.append({'filter_percent': percent, 'eligible_chunks': sum(len(m) for m in members),
                                       'eligible_chunks_per_shard': [len(m) for m in members], 'ef_search': ef,
                                       'mean_neighbor_recall': sum(values) / len(values), 'minimum_neighbor_recall': min(values),
                                       'observations': observations})
                finally:
                    for item, original in zip(built, originals):
                        item['real'].configuration = original
                        item['real'].save(update_fields=['configuration'])
            return result

        mark = time.monotonic()
        measured = relevance()
        timings['relevance_seconds'] = round(time.monotonic() - mark, 3)
        mark = time.monotonic()
        neighbors = ann()
        timings['ann_seconds'] = round(time.monotonic() - mark, 3)
        quality = measured['real']['metrics'][primary]
        if phase == 'development':
            minimum = max(measured[mode]['metrics'][primary] for mode in BASELINES)
            qualified = [ef for ef in ann_policy['ef_search']
                         if all(r['mean_neighbor_recall'] >= .95 for r in neighbors if r['ef_search'] == ef)]
            thresholds = {'minimum_relevance': minimum, 'chosen_ef_search': min(qualified) if qualified else None,
                          'source': 'development baselines and development ANN only'}
            outcome = {'ready_to_freeze': thresholds['chosen_ef_search'] is not None and quality > minimum}
        else:
            outcome = {'passed': (thresholds['chosen_ef_search'] is not None and quality > thresholds['minimum_relevance']
                                  and all(quality > measured[mode]['metrics'][primary] for mode in BASELINES))}
        try:
            commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
            status = subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True)
        except (OSError, subprocess.CalledProcessError):
            commit, status = 'unavailable', 'unavailable'
        with connection.cursor() as cursor:
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname='vector'")
            pgvector = cursor.fetchone()[0]
            cursor.execute('SHOW server_version')
            postgres = cursor.fetchone()[0]
        return {'schema': 'modelanvil.retrieval-expanded-check.v1', 'label': LABEL, 'phase': phase, 'commit': commit,
                'git_status_porcelain': status, 'frozen_input_commits': commits, 'policy_id': current['id'],
                'policy_sha256': sha256(POLICY_PATH.read_bytes()), 'pins_sha256': sha256(PINS_PATH.read_bytes()),
                'plan_digest': plan_digest, 'qrels_sha256': plan['qrels_sha256'][phase], 'archive_pins': ARCHIVE_PINS,
                'size': plan['size'], 'queries_evaluated': len(rows), 'documents': len(docs),
                'titles_shortened_to_field_limit': sum(len(d['title']) > TITLE_FIELD_LIMIT for d in docs.values()),
                'shards': [{k: v for k, v in s.items() if k != 'document_ids'} for s in plan['shards']],
                'chunks': sum(len(item['chunks']) for item in built), 'model_pins': adapter.PINS, 'runtime': adapter.environment(),
                'hardware': {'system': platform.system(), 'release': platform.release(), 'architecture': platform.machine(),
                             'processor': platform.processor(), 'cpu_threads': torch.get_num_threads(), 'gpu_used': False},
                'database': {'postgresql': postgres, 'pgvector': pgvector},
                'index_parameters': RetrievalEngine(built[0]['real']).settings(ann_policy['cutoff_chunks'])['hnsw'],
                'baselines': BASELINES, 'relevance': measured, 'thresholds': thresholds,
                'thresholds_source': 'computed from this development run' if phase == 'development' else 'committed development thresholds',
                **outcome,
                'ann_neighbor_recall': {'results': neighbors, 'exact_fallback_enabled': False,
                                        'unit': 'chunk-neighbor overlap inside each shard, separate from document relevance'},
                'timings': timings, 'elapsed_seconds': round(time.monotonic() - started, 3),
                'fixture_cleanup': 'owned temporary tenant, shards, vectors and HNSW indexes removed after evaluation'}
    finally:
        if tenant:
            # Only this newly generated, unkeyed benchmark tenant and its own indexes are owned by this run.
            with connection.cursor() as cursor:
                for name in indexes:
                    cursor.execute(f'DROP INDEX IF EXISTS {connection.ops.quote_name(name)}')
            for model in [QueryTrace, RetrievalRun, ChunkEmbedding, IndexVersion, KnowledgeBase, EmbeddingSpace, Project, Team]:
                model.all_objects.filter(tenant_id=tenant.pk).delete()
            tenant.delete()
        set_active_tenant(previous[0])
        set_active_project(previous[1])


def freeze(report, report_bytes):
    """The thresholds file written from a development report; commit it before the held-out run."""
    if report.get('phase') != 'development' or not report.get('ready_to_freeze'):
        raise ValueError('Only a development run with a qualified ANN effort and a model above its baselines can be frozen.')
    return {'schema': 'modelanvil.retrieval-expanded-thresholds.v1', 'label': LABEL, 'policy_id': report['policy_id'],
            'plan_digest': report['plan_digest'], 'source_phase': 'development', 'development_commit': report['commit'],
            'development_report_sha256': sha256(report_bytes), 'thresholds': report['thresholds'],
            'rule': policy()['thresholds']['development_rule'],
            'development_ndcg@5': {mode: report['relevance'][mode]['metrics']['ndcg@5'] for mode in MODES}}
