"""Explicit private Hub archive publication in a separate, narrowly scoped process."""
import hashlib
import json
from pathlib import Path
import re
import signal
import sys
from urllib.parse import urlsplit


def publish(request):
    from huggingface_hub import HfApi, set_client_factory
    import httpx
    path, repo, sha, token = Path(request['path']), request['repo_id'], request['sha256'], request['token']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', repo) or '..' in repo:
        raise ValueError('Invalid exact Hub target.')
    if not re.fullmatch('[a-f0-9]{64}', sha) or not token or request['authorize_sha256'] != sha:
        raise ValueError('Exact artifact authorization is required.')
    observed = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024): observed.update(block)
    if observed.hexdigest() != sha or not 1 <= path.stat().st_size <= 2 * 1024**3:
        raise ValueError('Archive identity changed.')
    origins = set(request['origins'])
    if 'https://huggingface.co' not in origins or any(urlsplit(v).scheme != 'https' or urlsplit(v).path not in ('', '/') for v in origins):
        raise ValueError('Install exact HTTPS publication origins.')
    def guard(http_request):
        address = urlsplit(str(http_request.url))
        origin = f'{address.scheme}://{address.netloc}'
        if origin not in origins or address.username or address.password:
            raise ValueError('Publication destination is outside the installed allowlist.')
        http_request.headers.pop('Cookie', None)
        if origin != 'https://huggingface.co':
            http_request.headers.pop('Authorization', None)
            if http_request.method not in {'GET', 'HEAD', 'PUT', 'POST'}:
                raise ValueError('Unsupported blob publication method.')
        elif http_request.method not in {'GET', 'HEAD'}:
            allowed = {f'/api/models/{repo}/preupload/main', f'/api/models/{repo}/commit/main',
                       f'/{repo}.git/info/lfs/objects/batch'}
            if http_request.method != 'POST' or address.path not in allowed:
                raise ValueError('Publication may only add the authorized immutable archive.')
    set_client_factory(lambda: httpx.Client(trust_env=False, follow_redirects=False, timeout=60,
                                           event_hooks={'request': [guard]}))
    api = HfApi(endpoint='https://huggingface.co', token=token, library_name='modelanvil')
    if api.whoami()['auth']['accessToken']['role'] != 'fineGrained':
        raise ValueError('Use a dedicated fine-grained repository write credential.')
    info = api.model_info(repo_id=repo, revision='main')
    if info.private is not True:
        raise ValueError('This bounded publication profile requires an existing private model repository.')
    filename = f'exports/{sha}.zip'
    def remote(revision):
        files = api.get_paths_info(repo_id=repo, paths=[filename], revision=revision)
        if not files: return False
        file = files[0]
        if file.path != filename or file.size != path.stat().st_size or not file.lfs or file.lfs.sha256 != sha:
            raise ValueError('Remote immutable archive path has conflicting or unverifiable bytes.')
        return True
    recovered = remote(info.sha)
    revision = info.sha
    if not recovered:
        result = api.upload_file(path_or_fileobj=str(path), path_in_repo=filename, repo_id=repo,
                                 repo_type='model', revision='main', parent_commit=info.sha,
                                 commit_message=f'Add immutable ModelAnvil export {sha}')
        revision = result.oid
        if not remote(revision): raise ValueError('The published commit does not contain the exact archive.')
    if not re.fullmatch('[a-f0-9]{40}', revision): raise ValueError('Hub returned no immutable commit identity.')
    return {'repo_id': repo, 'revision': revision, 'path': filename, 'sha256': sha,
            'byte_size': path.stat().st_size, 'private': True, 'recovered': recovered,
            'production_qualified': False}


if __name__ == '__main__':
    signal.alarm(600)
    try:
        request = json.loads(sys.stdin.read(16385))
        print(json.dumps(publish(request)))
    except Exception:
        # SDK errors may contain request headers or signed URLs; never echo them.
        print('Private Hub publication failed; no verified publication receipt.', file=sys.stderr)
        sys.exit(1)
