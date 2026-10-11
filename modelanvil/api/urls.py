"""API v1 URL routing.

The public API is mounted at ``/api/v1/`` (see ``modelanvil/urls.py``).
Exposes identity, tenancy, workers, datasets, training, evaluations,
alignment, RAG, Context Lab, releases, and operational endpoints.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from modelanvil.api.views import audit as audit_views
from modelanvil.api.views import annotation_views
from modelanvil.api.views import infrastructure_views
from modelanvil.api.views import context_lab_views
from modelanvil.api.views import health as api_health
from modelanvil.api.views import identity as identity_views
from modelanvil.api.views import jobs_artifacts as resource_views
from modelanvil.api.views import models_evals
from modelanvil.api.views import openapi as openapi_views
from modelanvil.api.views import rag_views
from modelanvil.api.views import registries as registry_views
from modelanvil.api.views import release_views
from modelanvil.api.views import run_detail_views
from modelanvil.api.views import training_views
from modelanvil.api.views import worker_artifacts as worker_artifact_views
from modelanvil.api.views import workers as worker_views
from modelanvil.data.bank import views as bank_views

router = DefaultRouter()
# Identity & Tenancy
router.register("tenants", identity_views.TenantViewSet, basename="tenant")
router.register("users", identity_views.UserViewSet, basename="user")
router.register("api-keys", identity_views.ApiKeyViewSet, basename="api-key")
router.register("memberships", identity_views.MembershipViewSet, basename="membership")
router.register("teams", identity_views.TeamViewSet, basename="team")
router.register("projects", identity_views.ProjectViewSet, basename="project")
router.register("team-memberships", identity_views.TeamMembershipViewSet, basename="team-membership")
router.register("project-memberships", identity_views.ProjectMembershipViewSet, basename="project-membership")
router.register("project-configs", identity_views.ProjectConfigViewSet, basename="project-config")
router.register("project-grants", identity_views.ProjectGrantViewSet, basename="project-grant")

# Data & Registries
router.register("data-sources", registry_views.DataSourceViewSet, basename="data-source")
router.register("source-snapshots", registry_views.SourceSnapshotViewSet, basename="source-snapshot")
router.register("runner-manifests", registry_views.RunnerManifestViewSet, basename="runner-manifest")
router.register("adapter-registry", registry_views.AdapterRegistryViewSet, basename="adapter-registry")
router.register("budget-policies", registry_views.BudgetPolicyViewSet, basename="budget-policy")
router.register("budget-reservations", registry_views.BudgetReservationViewSet, basename="budget-reservation")
router.register("usage-events", registry_views.UsageEventViewSet, basename="usage-event")
router.register("jobs", resource_views.JobViewSet, basename="job")
router.register("job-attempts", resource_views.JobAttemptViewSet, basename="job-attempt")
router.register("artifacts", resource_views.ArtifactViewSet, basename="artifact")
router.register("datasets", resource_views.DatasetViewSet, basename="dataset")
router.register("dataset-revisions", resource_views.DatasetRevisionViewSet, basename="dataset-revision")
router.register("dataset-bank", bank_views.DatasetBankViewSet, basename="dataset-bank")
router.register("audit", audit_views.AuditEventViewSet, basename="audit")
router.register("labeling-campaigns", annotation_views.CampaignViewSet, basename="labeling-campaign")
router.register("labeling-batches", annotation_views.BatchViewSet, basename="labeling-batch")
router.register("annotation-tasks", annotation_views.TaskViewSet, basename="annotation-task")
router.register("annotation-snapshots", annotation_views.SnapshotViewSet, basename="annotation-snapshot")
router.register("worker-pools", infrastructure_views.PoolViewSet, basename="worker-pool")
router.register("worker-inventory", infrastructure_views.WorkerViewSet, basename="worker-inventory")

# Models & Evaluations
router.register("models", models_evals.ModelViewSet, basename="model")
router.register("model-versions", models_evals.ModelVersionViewSet, basename="model-version")
router.register("tokenizers", models_evals.TokenizerVersionViewSet, basename="tokenizer")
router.register("evaluation-suites", models_evals.EvaluationSuiteViewSet, basename="evaluation-suite")
router.register("evaluation-suite-versions", models_evals.EvaluationSuiteVersionViewSet, basename="evaluation-suite-version")
router.register("evaluation-runs", models_evals.EvaluationRunViewSet, basename="evaluation-run")

# Training & Alignment
router.register("training-runs", training_views.TrainingRunViewSet, basename="training-run")
router.register("alignment-runs", training_views.AlignmentRunViewSet, basename="alignment-run")

# RAG & Context Lab
router.register("knowledge-bases", rag_views.KnowledgeBaseViewSet, basename="knowledge-base")
router.register("index-versions", rag_views.IndexVersionViewSet, basename="index-version")
router.register("context-recipes", context_lab_views.ContextRecipeViewSet, basename="context-recipe")
router.register("context-recipe-versions", context_lab_views.ContextRecipeVersionViewSet, basename="context-recipe-version")
router.register("context-experiments", context_lab_views.ContextExperimentViewSet, basename="context-experiment")

# Releases & Serving
router.register("releases", release_views.ReleaseViewSet, basename="release")
router.register("release-versions", release_views.ReleaseVersionViewSet, basename="release-version")
router.register("serving-endpoints", release_views.ServingEndpointViewSet, basename="serving-endpoint")

urlpatterns = [
    path("health/", api_health.health, name="api-health"),
    path("openapi.json", openapi_views.openapi_spec, name="api-openapi"),
    path("workers/artifact-grants/", worker_artifact_views.issue, name="worker-artifact-grant-issue"),
    path("workers/artifact-grants/discover/", worker_artifact_views.discover,
         name="worker-artifact-grant-discover"),
    path("workers/artifact-grants/<uuid:grant_id>/revoke/", worker_artifact_views.revoke,
         name="worker-artifact-grant-revoke"),
    path("workers/artifact-grants/<uuid:grant_id>/download/", worker_artifact_views.download,
         name="worker-artifact-download"),
    path("workers/", include(worker_views.urls)),
    path("", include(run_detail_views.urlpatterns)),
    path("", include(router.urls)),
]
