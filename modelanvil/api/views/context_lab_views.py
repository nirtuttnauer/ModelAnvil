"""Tenant-scoped REST APIs for Context Lab Recipes, Compiler, and Stress Experiments."""
from __future__ import annotations

from django.db import transaction
from rest_framework import serializers, status
from modelanvil.core.tenancy import get_active_tenant
from modelanvil.core.models import record_audit
from rest_framework.decorators import action
from rest_framework.response import Response

from modelanvil.api.views.registries import TenantScopedViewSet
from modelanvil.context_lab.compiler import ContextCompiler, ContextOverflowError
from modelanvil.context_lab.experiments import ContextExperimentRunner
from modelanvil.context_lab.models import (
    ContextBlockRevision,
    ContextExperiment,
    ContextRecipe,
    ContextRecipeVersion,
)


class ContextBlockRevisionSerializer(serializers.ModelSerializer):
    block_revision_id = serializers.UUIDField(source="block_id", read_only=True)

    priority = serializers.IntegerField(default=1, min_value=1, max_value=10)
    max_tokens = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=1000000)
    content_template = serializers.CharField(required=False, allow_blank=True, max_length=200000, trim_whitespace=False)

    class Meta:
        model = ContextBlockRevision
        fields = ("block_revision_id", "block_key", "block_type", "role", "priority", "order", "content_template", "max_tokens")


class ContextVersionInputSerializer(serializers.Serializer):
    model_limit_tokens = serializers.IntegerField(default=4096, min_value=1, max_value=1000000)
    output_reserve_tokens = serializers.IntegerField(default=512, min_value=0, max_value=1000000)
    budget_policy = serializers.ChoiceField(choices=("fail_on_overflow", "trim_lowest_priority"), default="trim_lowest_priority")
    blocks = ContextBlockRevisionSerializer(many=True, allow_empty=False, max_length=100)

    def validate(self, data):
        if data["output_reserve_tokens"] >= data["model_limit_tokens"]:
            raise serializers.ValidationError({"output_reserve_tokens": "Reserve must be smaller than the model limit."})
        keys = [block["block_key"] for block in data["blocks"]]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError({"blocks": "Block keys must be unique."})
        if sum(len(block.get("content_template", "")) for block in data["blocks"]) > 500000:
            raise serializers.ValidationError({"blocks": "Save at most 500,000 characters of context."})
        return data


def create_version(data, tenant_id):
    blocks = data.pop("blocks", [])
    version = ContextRecipeVersion.objects.create(tenant_id=tenant_id, **data)
    ContextBlockRevision.objects.bulk_create([
        ContextBlockRevision(tenant_id=tenant_id, recipe_version=version, **block) for block in blocks
    ])
    return version


class ContextRecipeVersionSerializer(serializers.ModelSerializer):
    blocks = ContextBlockRevisionSerializer(many=True, allow_empty=False, max_length=100)
    model_limit_tokens = serializers.IntegerField(default=4096, min_value=1, max_value=1000000)
    output_reserve_tokens = serializers.IntegerField(default=512, min_value=0, max_value=1000000)
    revision_no = serializers.IntegerField(default=1, min_value=1)

    def validate(self, data):
        if data.get("output_reserve_tokens", 512) >= data.get("model_limit_tokens", 4096):
            raise serializers.ValidationError({"output_reserve_tokens": "Reserve must be smaller than the model limit."})
        if "blocks" in data:
            ContextVersionInputSerializer(data={key: data[key] for key in ("blocks", "model_limit_tokens", "output_reserve_tokens", "budget_policy") if key in data}).is_valid(raise_exception=True)
        if data.get("budget_policy") == "summarize":
            raise serializers.ValidationError({"budget_policy": "Automatic summarization has no configured model executor."})
        return data

    @transaction.atomic
    def create(self, validated_data):
        tenant_id = validated_data.pop("tenant_id")
        ContextRecipe.objects.select_for_update().get(pk=validated_data["recipe"].pk)
        if ContextRecipeVersion.objects.filter(recipe=validated_data["recipe"], revision_no=validated_data.get("revision_no", 1)).exists():
            raise serializers.ValidationError({"revision_no": "This revision already exists; create a new revision number."})
        return create_version(validated_data, tenant_id)

    class Meta:
        model = ContextRecipeVersion
        fields = (
            "recipe_version_id", "recipe", "revision_no", "model_limit_tokens",
            "output_reserve_tokens", "budget_policy", "blocks", "created_at"
        )
        read_only_fields = ("recipe_version_id", "created_at")


class ContextRecipeSerializer(serializers.ModelSerializer):
    versions = ContextRecipeVersionSerializer(many=True, read_only=True)
    initial_version = ContextVersionInputSerializer(write_only=True, required=False)

    def validate_name(self, value):
        existing = ContextRecipe.objects.filter(tenant_id=get_active_tenant(), name=value)
        if self.instance:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError("A recipe with this name already exists.")
        return value

    def validate(self, data):
        if self.instance and "initial_version" in data:
            raise serializers.ValidationError({"initial_version": "Create a new version through the recipe versions endpoint."})
        return data

    @transaction.atomic
    def create(self, validated_data):
        version = validated_data.pop("initial_version", None)
        recipe = super().create(validated_data)
        if version:
            create_version({"recipe": recipe, "revision_no": 1, **version}, recipe.tenant_id)
        return recipe


    class Meta:
        model = ContextRecipe
        fields = ("id", "recipe_id", "name", "description", "initial_version", "versions", "created_at", "updated_at")
        read_only_fields = ("id", "recipe_id", "versions", "created_at", "updated_at")


class ContextRecipeViewSet(TenantScopedViewSet):
    queryset = ContextRecipe.objects.prefetch_related("versions")
    serializer_class = ContextRecipeSerializer
    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)
        record_audit("create", "context_recipe", serializer.instance.recipe_id,
                     actor_id=getattr(self.request, "modelanvil_actor_id", None), actor_kind=getattr(self.request, "modelanvil_actor_kind", "system"),
                     input_snapshot={"version_count": serializer.instance.versions.count()})

    lookup_field = "recipe_id"
    http_method_names = ["get", "post", "patch", "head", "options"]


class ContextRecipeVersionViewSet(TenantScopedViewSet):
    queryset = ContextRecipeVersion.objects.prefetch_related("blocks")
    serializer_class = ContextRecipeVersionSerializer
    @transaction.atomic
    def perform_create(self, serializer):
        super().perform_create(serializer)
        record_audit("create", "context_recipe_version", serializer.instance.recipe_version_id,
                     actor_id=getattr(self.request, "modelanvil_actor_id", None), actor_kind=getattr(self.request, "modelanvil_actor_kind", "system"),
                     input_snapshot={"revision_no": serializer.instance.revision_no, "block_count": serializer.instance.blocks.count()})

    lookup_field = "recipe_version_id"
    http_method_names = ["get", "post", "head", "options"]

    def initial(self, request, *args, **kwargs):
        if self.action == "compile_prompt":
            from modelanvil.identity.models import Role
            self.write_role = Role.VIEWER
        return super().initial(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="compile")
    def compile_prompt(self, request, recipe_version_id=None):
        """Compile context blocks with dynamic template variables and token budget allocation."""
        version = self.get_object()
        variables = request.data.get("variables", {})
        if not isinstance(variables, dict) or len(variables) > 100 or any(not isinstance(value, str) for value in variables.values()) or sum(len(value) for value in variables.values()) > 500000:
            return Response({"detail": "Variables must be an object of at most 100 text blocks and 500,000 characters."}, status=status.HTTP_400_BAD_REQUEST)
        compiler = ContextCompiler(version)
        try:
            result = compiler.compile(variables)
            return Response({
                "serialized_prompt": result.serialized_prompt,
                "token_count": result.total_input_tokens,
                "included_blocks": [block.block_key for block in result.included_blocks],
                "dropped_blocks": [block["block_key"] for block in result.omitted_blocks],
                "budget_exhausted": bool(result.omitted_blocks or result.truncated_blocks),
                "omitted_blocks": result.omitted_blocks,
                "truncated_blocks": result.truncated_blocks,
                "block_token_counts": [{"block_key": block.block_key, "token_count": block.token_count, "truncated": block.truncated} for block in result.included_blocks],
                "token_count_method": "deterministic_estimate",
                "output_reserve_tokens": result.output_reserve_tokens,
                "model_limit_tokens": result.model_limit_tokens,
            })
        except ContextOverflowError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="sweep")
    def position_sweep(self, request, recipe_version_id=None):
        """Execute lost-in-the-middle evidence position sweep experiment."""
        version = self.get_object()
        fact = request.data.get("target_fact", "Target key phrase 42.")
        runner = ContextExperimentRunner(version)
        exp = runner.run_evidence_position_sweep(target_fact=fact)
        return Response({
            "experiment_id": str(exp.experiment_id),
            "metrics": exp.metrics,
            "details": exp.details,
        })


class ContextExperimentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContextExperiment
        fields = ("experiment_id", "recipe_version", "name", "stress_type", "metrics", "details", "created_at")
        read_only_fields = ("experiment_id", "created_at")


class ContextExperimentViewSet(TenantScopedViewSet):
    queryset = ContextExperiment.objects.all()
    serializer_class = ContextExperimentSerializer
    lookup_field = "experiment_id"
