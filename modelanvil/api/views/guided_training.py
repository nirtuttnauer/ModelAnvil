"""The guided browser path selects verified local training resources automatically."""
from functools import lru_cache

from django.conf import settings
from rest_framework import permissions, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role, Project, role_at_least
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.managed import host_status, prepare_resources, verified_model_directory, recommended_source


class GuidedOptions(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from modelanvil.runners.capabilities import training_memory_requirements
        source = recommended_source(); large = source == hf_runtime.LARGE_GUIDED_SOURCE
        return Response({'compute': host_status(), 'model': {'id': source['repo_id'].split('/')[-1].lower(), 'name': source['repo_id'].split('/')[-1].replace('-Instruct', ' Instruct'),
            'description': 'An instruction model selected for this computer. Lightweight adapters adapt its answers while keeping the base weights frozen.' if large else 'A small model that already follows instructions. Fine-tuning adapts its answers to your examples.',
            'parameters': 1700000000 if large else 135000000,
            'license': source['license'], 'source': source,
            'max_examples': hf_runtime.LIMITS['rows'], 'max_tokens': hf_runtime.LIMITS['sequence_tokens'],
            'memory_requirements': {'weights_bytes': None, 'training': training_memory_requirements(hf_runtime.RUNTIME_ID, source)}},
            'default_epochs': 3, 'small_adapter_epochs': 6, 'max_steps': 3000})


class GuidedSetup(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRBAC]
    required_role = Role.ENGINEER

    def post(self, request):
        selected = recommended_source()['repo_id'].split('/')[-1].lower()
        if request.data.get('model', selected) not in (selected, 'smollm2-135m' if selected == 'smollm2-135m-instruct' else selected):
            raise serializers.ValidationError('Refresh the recommended model for this computer, then choose it again.')
        project = get_active_project()
        if not project or not Project.all_objects.filter(pk=project, tenant_id=get_active_tenant()).exists():
            raise serializers.ValidationError('Select a project before preparing your model.')
        try:
            return Response({'inputs': prepare_resources(get_active_tenant(), project, allow_new_allowance=role_at_least(getattr(request, 'modelanvil_role', None), Role.ADMIN))})
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from None


@lru_cache(maxsize=2)
def local_tokenizer(directory, build):
    return hf_runtime._tokenizer(directory)


def preview_training(raw, source_mapping=None):
    from modelanvil.data.publication import prepare_source, DatasetPreparationError
    from modelanvil.data.training_import import tokenize_blocks
    prepared, _ = prepare_source(raw, source_format='training', source_mapping=source_mapping, dedup={'exact': True, 'near': False})
    directory = verified_model_directory()
    tokenizer = local_tokenizer(str(directory), hf_runtime.CONTRACT_DIGEST)
    objectives = set()
    for number, row in enumerate(prepared['rows'], 1):
        try:
            _, tokens, labels = tokenize_blocks(row['blocks'], tokenizer)
            if not 2 <= len(tokens) <= hf_runtime.LIMITS['sequence_tokens']:
                raise ValueError(f'This example contains {len(tokens)} tokens; shorten it to 2–128 tokens. Nothing was truncated.')
        except ValueError as exc:
            raise DatasetPreparationError(f'Example {number}: {exc}') from None
        objectives.add('assistant responses' if labels != tokens else 'all text tokens')
    return {'row_count': prepared['row_count'], 'source_group_count': prepared['source_group_count'],
            'split_counts': {k: len(v) for k, v in prepared['split_manifest'].items()},
            'examples': [r['blocks'] for r in prepared['rows'][:3]], 'objectives': sorted(objectives),
            'sample_rows': [{**row, 'assigned_split': next((split for split, ids in prepared['split_manifest'].items() if row['sample_id'] in ids), None)} for row in prepared['rows'][:5]],
            'recipe_digest': prepared['recipe_digest'], 'dropped_count': len(prepared.get('dropped', [])),
            'warnings': [] if prepared['source_group_count'] >= 3 else
                        ['Fewer than three independent groups: all examples stay in training. Add more examples for held-out validation and testing.']}


class GuidedPreview(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRBAC]
    required_role = Role.ENGINEER

    def post(self, request):
        from modelanvil.data.publication import MAX_INPUT_BYTES
        file = request.data.get('file')
        if file is None or not hasattr(file, 'read') or not 0 < file.size <= MAX_INPUT_BYTES:
            raise serializers.ValidationError('Choose a nonempty JSONL, JSON or CSV file of at most 16 MiB.')
        try:
            import json
            mapping = request.data.get('source_mapping')
            if isinstance(mapping, str):
                mapping = json.loads(mapping)
            return Response(preview_training(file.read(MAX_INPUT_BYTES + 1), mapping))
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from None


class GuidedSourceInspect(APIView):
    permission_classes = [permissions.IsAuthenticated, TenantRBAC]
    required_role = Role.ENGINEER

    def post(self, request):
        from modelanvil.data.publication import MAX_INPUT_BYTES
        from modelanvil.data.training_import import inspect_training_source
        file = request.data.get('file')
        if file is None or not hasattr(file, 'read') or not 0 < file.size <= MAX_INPUT_BYTES:
            raise serializers.ValidationError('Choose a nonempty JSONL, JSON or CSV file of at most 16 MiB.')
        try:
            import json
            mapping = request.data.get('source_mapping')
            if isinstance(mapping, str):
                mapping = json.loads(mapping)
            return Response(inspect_training_source(file.read(MAX_INPUT_BYTES + 1), mapping))
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from None
