"""Model discovery, immutable acquisition and local chat completion APIs."""
from contextlib import ExitStack
from contextvars import copy_context
import json
import time
import uuid

from django.db import IntegrityError
from django.http import StreamingHttpResponse
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.core.tenancy import get_active_project, get_active_tenant
from modelanvil.identity.models import Project
from modelanvil.jobs.models import WorkerPool
from modelanvil.runners import model_catalog
from modelanvil.runners.inference import generate, local_session, validate_messages
from modelanvil.runners.models import ChatComparison, ChatConversation, InferenceRequest, ModelImport, ModelVersion
from modelanvil.identity.models import get_accessible_queryset


def selected_project():
    project = Project.all_objects.filter(pk=get_active_project(), tenant_id=get_active_tenant()).first()
    if project is None:
        raise serializers.ValidationError({'project': 'Select a project before acquiring or serving models.'})
    return project


class ImportInput(serializers.Serializer):
    name = serializers.CharField(max_length=180)
    repo_id = serializers.CharField(max_length=200, required=False)
    revision = serializers.RegexField(r'^[a-f0-9]{40}$', required=False)
    format = serializers.ChoiceField(choices=['safetensors', 'gguf', 'mlx'], required=False)
    filename = serializers.CharField(max_length=180, required=False)
    pool = serializers.IntegerField(min_value=1, required=False)
    accepted_license = serializers.CharField(max_length=200)
    idempotency_key = serializers.CharField(max_length=128)
    files = serializers.JSONField(required=False)


class ImportSerializer(serializers.ModelSerializer):
    job_id = serializers.UUIDField(source='job.job_id', read_only=True, allow_null=True)
    job_status = serializers.CharField(source='job.status', read_only=True, allow_null=True)
    candidate_id = serializers.UUIDField(source='candidate.model_version_id', read_only=True, allow_null=True)

    class Meta:
        model = ModelImport
        fields = ['import_id', 'name', 'repo_id', 'revision', 'format', 'license_expression',
                  'files', 'acquired_files', 'job_id', 'job_status', 'candidate_id', 'status', 'created_at']
        read_only_fields = fields


class ModelImportViewSet(TenantScopedViewSet):
    queryset = ModelImport.objects.select_related('job', 'candidate')
    serializer_class = ImportSerializer
    lookup_field = 'import_id'
    http_method_names = ['get', 'post', 'head', 'options']

    def _change(self, request, action_name):
        from modelanvil.runners.import_recovery import change_import
        from modelanvil.core.models import record_audit
        try:
            item = change_import(self.get_object(), action_name)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        record_audit(f'model_import.{action_name}', 'model_import', item.import_id,
            actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
            input_snapshot={'job_id': str(item.job.job_id), 'job_status': item.job.status, 'verified_files': len(item.acquired_files)})
        return Response(ImportSerializer(item).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, import_id=None):
        return self._change(request, 'cancel')

    @action(detail=True, methods=['post'])
    def resume(self, request, import_id=None):
        return self._change(request, 'resume')

    @action(detail=False, methods=['get'])
    def search(self, request):
        project = selected_project()
        try:
            return Response({'results': model_catalog.search_models(request.query_params.get('q'), get_active_tenant(), project.pk)})
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    @action(detail=False, methods=['post'])
    def inspect(self, request):
        project = selected_project()
        try:
            plan = model_catalog.inspect_model(request.data.get('repo_id'), request.data.get('revision'),
                get_active_tenant(), project.pk, format=request.data.get('format', 'safetensors'), filename=request.data.get('filename'))
            return Response(plan)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    @action(detail=False, methods=['post'], url_path='upload-file')
    def upload_file(self, request):
        project = selected_project()
        file = request.data.get('file')
        if file is None or not hasattr(file, 'read') or not model_catalog.filename_allowed(file.name):
            raise serializers.ValidationError('Upload a supported model or tokenizer filename.')
        if not 0 < file.size <= model_catalog.MAX_BYTES:
            raise serializers.ValidationError('Model files must contain 1 byte–8 GiB.')
        try:
            ref = model_catalog._store(file, tenant=get_active_tenant(), project=project.pk, name=file.name, size=file.size)
            return Response({'filename': file.name, **ref}, status=201)
        except (ValueError, OSError) as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def create(self, request):
        project = selected_project()
        form = ImportInput(data=request.data); form.is_valid(raise_exception=True)
        data = form.validated_data
        try:
            if 'files' in data:
                item = model_catalog.import_local(data['files'], tenant=get_active_tenant(), project=project,
                    name=data['name'], license_expression=data['accepted_license'], idempotency_key=data['idempotency_key'], format=data.get('format'))
            else:
                pool = WorkerPool.all_objects.filter(pk=data.get('pool'), tenant_id=get_active_tenant()).first()
                if pool is None:
                    raise ValueError('Select a model-import worker pool.')
                # Reinspect immutable upstream metadata; clients cannot edit the download plan.
                plan = model_catalog.inspect_model(data.get('repo_id'), data.get('revision'), get_active_tenant(), project.pk,
                    format=data.get('format', 'safetensors'), filename=data.get('filename'))
                item = model_catalog.launch_import(plan, tenant=get_active_tenant(), project=project, pool=pool,
                    name=data['name'], idempotency_key=data['idempotency_key'], accepted_license=data['accepted_license'])
            return Response(ImportSerializer(item).data, status=201)
        except (ValueError, OSError) as exc:
            raise serializers.ValidationError(str(exc)) from exc
        except IntegrityError:
            raise serializers.ValidationError('A model with this name or import key already exists.') from None


class CompletionInput(serializers.Serializer):
    model = serializers.UUIDField()
    messages = serializers.JSONField()
    max_tokens = serializers.IntegerField(min_value=1, max_value=256, default=128)
    temperature = serializers.FloatField(min_value=0, max_value=2, default=0)
    seed = serializers.IntegerField(min_value=0, max_value=2147483647, default=42)
    device = serializers.CharField(max_length=40, default='cpu')
    stream = serializers.BooleanField(default=False)
    prompt_format = serializers.ChoiceField(choices=['model', 'plain', 'chatml'], default='model')
    stream_options = serializers.JSONField(required=False)

    def validate_messages(self, value):
        try:
            return validate_messages(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        unknown = set(self.initial_data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError('Unsupported completion options: ' + ', '.join(sorted(unknown)))
        options = attrs.get('stream_options', {})
        if not isinstance(options, dict) or set(options) - {'include_usage'} or ('include_usage' in options and type(options['include_usage']) is not bool):
            raise serializers.ValidationError('stream_options supports only include_usage: true/false.')
        return attrs


class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatConversation
        fields = ['conversation_id', 'title', 'messages', 'configuration', 'revision_no', 'created_at', 'updated_at']
        read_only_fields = ['conversation_id', 'created_at', 'updated_at']

    def validate_messages(self, value):
        try:
            if not isinstance(value, list):
                raise ValueError('Conversation messages must be a list.')
            return validate_messages(value) if value else []
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate_configuration(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError('Conversation configuration must be an object.')
        data = {**value, 'messages': [{'role': 'user', 'content': 'validation'}]}
        data.pop('system_prompt', None)
        data.pop('compare_model', None)
        data.pop('compare_device', None)
        serializers.ChoiceField(choices=['blind', 'base-trained']).run_validation(data.pop('comparison_mode', 'blind'))
        form = CompletionInput(data=data); form.is_valid(raise_exception=True)
        models = [value.get('model'), value.get('compare_model')]
        from modelanvil.identity.models import get_accessible_queryset
        for identifier in filter(None, models):
            try:
                identifier = serializers.UUIDField().run_validation(identifier)
                exists = get_accessible_queryset(ModelVersion).filter(model_version_id=identifier).exists()
            except (ValueError, TypeError, serializers.ValidationError):
                exists = False
            if not exists:
                raise serializers.ValidationError('Select an accessible model version.')
        prompt = value.get('system_prompt', '')
        if not isinstance(prompt, str) or len(prompt) > 8000:
            raise serializers.ValidationError('System prompt must fit within 8,000 characters.')
        return value


class ConversationViewSet(TenantScopedViewSet):
    queryset = ChatConversation.objects.all()
    serializer_class = ConversationSerializer
    lookup_field = 'conversation_id'
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']

    def perform_create(self, serializer):
        serializer.save(tenant_id=get_active_tenant(), project=selected_project(), revision_no=1)

    def perform_update(self, serializer):
        from django.db import transaction
        from modelanvil.core.exceptions import WorkflowConflict
        with transaction.atomic():
            current = self.get_queryset().select_for_update().get(pk=serializer.instance.pk)
            if serializer.validated_data.get('revision_no') != current.revision_no:
                raise WorkflowConflict('This conversation changed; refresh before saving.')
            serializer.instance = current
            serializer.save(revision_no=current.revision_no + 1)


class ComparisonInput(serializers.Serializer):
    conversation_id = serializers.UUIDField()
    messages = serializers.JSONField()
    responses = serializers.ListField(child=serializers.DictField(), min_length=2, max_length=2)


class ComparisonSerializer(serializers.ModelSerializer):
    review_campaign_id = serializers.UUIDField(source='review_campaign.campaign_id', read_only=True, allow_null=True)
    conversation_id = serializers.UUIDField(source='conversation.conversation_id', read_only=True, allow_null=True)
    sides = serializers.SerializerMethodField()

    def get_sides(self, comparison):
        roles = {}
        if self.context.get('request') and self.context['request'].query_params.get('view') == 'base-trained':
            from django.db.models import Q
            from modelanvil.runners.models import TrainingRun
            first, second = comparison.first_request.model_version_id, comparison.second_request.model_version_id
            lineage = get_accessible_queryset(TrainingRun).filter(status='completed', job__status='succeeded').filter(
                Q(base_model_version_id=first, output_model_version_id=second) | Q(base_model_version_id=second, output_model_version_id=first)).first()
            if lineage:
                roles = {lineage.base_model_version_id: 'base', lineage.output_model_version_id: 'trained'}
        sides = []
        for label, first in (('A', comparison.first_is_a), ('B', not comparison.first_is_a)):
            request = comparison.first_request if first else comparison.second_request
            value = {'label': label, 'text': comparison.first_text if first else comparison.second_text}
            if comparison.vote or roles:
                value.update(model=str(request.model_version.model_version_id), name=request.model_version.model.name,
                    usage=request.usage, elapsed_seconds=request.elapsed_seconds, configuration=request.configuration)
            if roles:
                value['role'] = roles[request.model_version_id]
            sides.append(value)
        return sides

    class Meta:
        model = ChatComparison
        fields = ['comparison_id', 'conversation_id', 'messages', 'sides', 'vote', 'created_at', 'voted_at', 'review_campaign_id']
        read_only_fields = fields


class ComparisonViewSet(TenantScopedViewSet):
    queryset = ChatComparison.objects.select_related('conversation', 'first_request__model_version__model', 'second_request__model_version__model')
    serializer_class = ComparisonSerializer
    lookup_field = 'comparison_id'
    http_method_names = ['get', 'post', 'head', 'options']

    def get_queryset(self):
        selected_project()
        versions = get_accessible_queryset(ModelVersion).values('pk')
        return super().get_queryset().filter(first_request__model_version_id__in=versions,
            second_request__model_version_id__in=versions)

    def create(self, request):
        import hashlib
        import secrets
        from django.db import transaction
        from modelanvil.runners.training.runtime import digest
        project = selected_project()
        form = ComparisonInput(data=request.data); form.is_valid(raise_exception=True)
        value = form.validated_data
        try:
            messages = validate_messages(value['messages'])
            conversation = ConversationViewSet.queryset.filter(tenant_id=get_active_tenant(), project=project,
                conversation_id=value['conversation_id']).first()
            if conversation is None:
                raise ValueError('Select a conversation in this project.')
            results = []
            for response in value['responses']:
                if set(response) != {'request_id', 'text'} or not isinstance(response['text'], str) or len(response['text']) > 32000:
                    raise ValueError('Each response needs its request ID and bounded actual output text.')
                identifier = serializers.UUIDField().run_validation(response['request_id'])
                record = InferenceRequest.all_objects.filter(request_id=identifier, tenant_id=get_active_tenant(),
                    project=project, principal_id=str(request.user.pk), status='completed',
                    model_version__in=get_accessible_queryset(ModelVersion)).first()
                if record is None or record.input_digest != digest(messages):
                    raise ValueError('Use your completed requests for exactly the same comparison input.')
                expected = hashlib.sha256(response['text'].encode()).hexdigest() if response['text'] else ''
                if expected != record.output_digest:
                    raise ValueError('Comparison output differs from its measured inference request.')
                results.append((record, response['text']))
            (first, first_text), (second, second_text) = sorted(results, key=lambda item: str(item[0].request_id))
            if first.pk == second.pk or first.model_version_id == second.model_version_id:
                raise ValueError('Compare two distinct model versions and requests.')
            settings = lambda record: {k: v for k, v in record.configuration.items() if k not in {'device'}}
            if settings(first) != settings(second):
                raise ValueError('Comparison generation settings must match; devices may differ.')
            with transaction.atomic():
                comparison, created = ChatComparison.all_objects.get_or_create(first_request=first, second_request=second,
                    defaults={'tenant_id': get_active_tenant(), 'project': project, 'conversation': conversation,
                        'first_text': first_text, 'second_text': second_text, 'first_is_a': bool(secrets.randbelow(2)), 'messages': messages})
                if comparison.conversation_id != conversation.pk:
                    raise ValueError('This response pair is already saved to another conversation.')
            return Response(self.get_serializer(comparison).data, status=201 if created else 200)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    @action(detail=True, methods=['post'], url_path='review-batch')
    def review_batch(self, request, comparison_id=None):
        from modelanvil.annotation.arena_review import review_comparison
        from modelanvil.core.models import record_audit
        try: campaign, created = review_comparison(self.get_object())
        except ValueError as exc: raise serializers.ValidationError(str(exc)) from exc
        if created:
            record_audit('comparison.review', 'chat_comparison', self.get_object().comparison_id,
                actor_id=request.modelanvil_actor_id, actor_kind=request.modelanvil_actor_kind,
                input_snapshot={'campaign_id': str(campaign.campaign_id), 'qualification': 'awaiting_independent_human_review'})
        return Response({'campaign_id': str(campaign.campaign_id), 'status': 'awaiting_independent_human_review'}, status=201 if created else 200)

    @action(detail=True, methods=['post'])
    def vote(self, request, *args, **kwargs):
        from django.db import transaction
        from django.utils import timezone
        from modelanvil.core.exceptions import WorkflowConflict
        choice = serializers.ChoiceField(choices=['A', 'B', 'tie', 'neither']).run_validation(request.data.get('vote'))
        with transaction.atomic():
            comparison = self.get_queryset().select_for_update(of=('self',)).get(pk=self.get_object().pk)
            if comparison.vote:
                if comparison.vote != choice or comparison.voter_id != str(request.user.pk):
                    raise WorkflowConflict('This comparison already has a recorded preference.')
            else:
                comparison.vote, comparison.voter_id, comparison.voted_at = choice, str(request.user.pk), timezone.now()
                comparison.save(update_fields=['vote', 'voter_id', 'voted_at', 'updated_at'])
        return Response(self.get_serializer(comparison).data)


class CompletionStream:
    def __init__(self, iterator, stack, on_close):
        self.iterator, self.stack, self.on_close = iterator, stack, on_close
        self.closed = False
        self.context = copy_context()

    def __iter__(self):
        try:
            while True:
                try:
                    value = self.context.run(next, self.iterator)
                except StopIteration:
                    return
                yield value
        finally:
            self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.context.run(self.iterator.close)
            finally:
                self.context.run(self.stack.close)
                self.context.run(self.on_close)


class InferenceViewSet(TenantScopedViewSet):
    queryset = ModelVersion.objects.select_related('model', 'tokenizer')
    serializer_class = None
    http_method_names = ['get', 'post', 'head', 'options']

    def create(self, request):
        from rest_framework.exceptions import MethodNotAllowed
        raise MethodNotAllowed('POST')

    def retrieve(self, request, pk=None):
        from rest_framework.exceptions import NotFound
        raise NotFound()

    def list(self, request):
        selected_project()
        from django.db.models import Q
        from modelanvil.runners.models import TrainingRun
        from modelanvil.runners.training import hf_runtime, mlx_runtime, cpu_hf_runtime, runtime, general_runtime
        trained_runs = get_accessible_queryset(TrainingRun).filter(status='completed', job__status='succeeded',
            base_model_version__architecture_ref__in=[cpu_hf_runtime.RUNTIME_ID, hf_runtime.RUNTIME_ID, mlx_runtime.RUNTIME_ID, runtime.RUNTIME_ID, general_runtime.RUNTIME_ID]).select_related('base_model_version').order_by('-created_at', '-pk')
        lineage = {}
        for run in trained_runs:
            if run.output_model_version_id:
                lineage.setdefault(run.output_model_version_id, run)
        rows = self.get_queryset().filter(Q(metadata__imported=True) | Q(metadata__managed_local=True) | Q(pk__in=lineage) | Q(architecture_ref__in=[runtime.RUNTIME_ID, general_runtime.RUNTIME_ID])).exclude(architecture_ref__in=['modelanvil.ocr.v1', 'modelanvil.laya.v1'])
        from modelanvil.runners.capabilities import model_capabilities
        from modelanvil.runners.inference import model_chat_template
        eligible = [(v, model_capabilities(v)['chat']) for v in rows]
        eligible_ids = {str(v.model_version_id) for v, capability in eligible if capability['eligible']}
        return Response({'object': 'list', 'data': [{'id': str(v.model_version_id), 'object': 'model',
            'created': int(v.created_at.timestamp()), 'owned_by': 'modelanvil', 'name': v.model.name,
            'format': capability.get('format', v.metadata.get('format', 'safetensors')), 'load_tested': v.inference_requests.filter(status='completed').exists(),
            'devices': capability['devices'], 'max_tokens': capability['max_tokens'], 'context_limit': capability['context_limit'],
            'tokenizer_kind': capability.get('tokenizer_kind'),
            'training_run_id': str(lineage[v.pk].run_id) if v.pk in lineage else None,
            'base_model_id': str(lineage[v.pk].base_model_version.model_version_id) if v.pk in lineage and str(lineage[v.pk].base_model_version.model_version_id) in eligible_ids else None,
            'has_chat_template': bool(model_chat_template(v)), 'chat_template': model_chat_template(v)} for v, capability in eligible if capability['eligible']]})

    @action(detail=False, methods=['post'], url_path='chat/completions')
    def completions(self, request):
        project = selected_project()
        form = CompletionInput(data=request.data); form.is_valid(raise_exception=True)
        options = form.validated_data
        version = self.get_queryset().filter(model_version_id=options['model']).first()
        if version is None:
            from rest_framework.exceptions import NotFound
            raise NotFound('Model is unavailable in this project.')
        stack = ExitStack()
        from modelanvil.runners.training.runtime import digest
        record = InferenceRequest.all_objects.create(tenant_id=get_active_tenant(), project=project, model_version=version,
            principal_id=str(request.user.pk), input_digest=digest(options['messages']),
            configuration={k: v for k, v in options.items() if k not in {'messages', 'model'}})
        output = ''
        tenant = get_active_tenant()

        def assert_current():
            from modelanvil.identity.auth import ApiKeyAuthentication, TenantRBAC
            principal = ApiKeyAuthentication().authenticate(request)
            if (principal is None or principal[0].pk != request.user.pk
                    or get_active_tenant() != tenant or get_active_project() != project.pk
                    or not TenantRBAC().has_permission(request, self)):
                raise ValueError('Current inference access is unavailable.')
            guard()

        def record_finish(status, final=None):
            from django.utils import timezone
            import hashlib
            final = final or {}
            InferenceRequest.all_objects.filter(pk=record.pk, status='running').update(status=status,
                completed_at=timezone.now(), usage=final.get('usage'), elapsed_seconds=final.get('elapsed_seconds'),
                output_digest=hashlib.sha256(output.encode()).hexdigest() if output else '')

        try:
            from modelanvil.runners.inference import snapshot_guard
            guard = snapshot_guard(version, tenant, project.pk)
            session = stack.enter_context(local_session(version, tenant=get_active_tenant(), project=project.pk, device=options['device']))
            parts = generate(session, options['messages'], max_tokens=options['max_tokens'],
                             temperature=options['temperature'], seed=options['seed'], prompt_format=options['prompt_format'])
            first = next(parts)
            assert_current()
        except Exception as exc:
            stack.close()
            record_finish('failed')
            message = str(exc) if isinstance(exc, ValueError) else 'Model could not load or generate; check runtime compatibility and memory.'
            raise serializers.ValidationError(message) from exc
        identifier, created = 'chatcmpl-' + record.request_id.hex, int(time.time())
        base = {'id': identifier, 'created': created, 'model': str(version.model_version_id)}

        def events():
            nonlocal output
            from itertools import chain
            try:
                assert_current()
                yield 'data: ' + json.dumps({**base, 'object': 'chat.completion.chunk',
                    'choices': [{'index': 0, 'delta': {'role': 'assistant'}, 'finish_reason': None}]}) + '\n\n'
                for part in chain([first], parts):
                    assert_current()
                    output += part.get('text', '')
                    done = part.get('finish_reason')
                    chunk = {**base, 'object': 'chat.completion.chunk', 'choices': [{'index': 0,
                        'delta': {'content': part['text']} if 'text' in part else {}, 'finish_reason': done}]}
                    if done:
                        chunk['modelanvil'] = {'elapsed_seconds': part['elapsed_seconds'], 'device': options['device']}
                        record_finish('completed', part)
                    yield 'data: ' + json.dumps(chunk) + '\n\n'
                    if done and options.get('stream_options', {}).get('include_usage'):
                        assert_current()
                        yield 'data: ' + json.dumps({**base, 'object': 'chat.completion.chunk', 'choices': [], 'usage': part['usage']}) + '\n\n'
            except Exception:
                record_finish('failed')
                yield 'data: ' + json.dumps({'error': {'message': 'Local generation failed; inspect runtime compatibility.', 'type': 'inference_error'}}) + '\n\n'
            finally:
                parts.close()
                # Release admission before DONE lets clients start the next arena request.
                stack.close()
                record_finish('cancelled')
            yield 'data: [DONE]\n\n'

        if options['stream']:
            def closed():
                parts.close()
                record_finish('cancelled')
            response = StreamingHttpResponse(CompletionStream(events(), stack, closed), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache'
            response['X-Accel-Buffering'] = 'no'
            return response
        try:
            from itertools import chain
            text, final = '', {}
            for part in chain([first], parts):
                assert_current()
                text += part.get('text', '')
                if 'finish_reason' in part:
                    final = part
            output = text
            record_finish('completed', final)
            return Response({**base, 'object': 'chat.completion', 'choices': [{'index': 0,
                'message': {'role': 'assistant', 'content': text}, 'finish_reason': final['finish_reason']}],
                'usage': final['usage'], 'modelanvil': {'device': options['device'], 'elapsed_seconds': final['elapsed_seconds']}})
        except ValueError as exc:
            raise serializers.ValidationError('Model inputs or current access changed; output withheld.') from exc
        finally:
            parts.close()
            stack.close()
            record_finish('failed')
