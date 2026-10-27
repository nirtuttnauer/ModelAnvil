"""Current support numbers for the browser. This is not a qualification stamp."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modelanvil.core.pilot_gate import commercial_status
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role
from modelanvil.runners.evidence import LEVELS
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.cpu_hf_runtime import LIMITS as CPU_LIMITS
from modelanvil.runners.training.sequence_envelope import generated_token_ceiling


def ledger_payload():
    return {
        'documentation': '/docs/engineering/capability-ledger.md',
        'production_qualified': False,
        'hardware_qualified': False,
        'levels': LEVELS,
        'guided_sequence_tokens': hf_runtime.LIMITS['sequence_tokens'],
        'cpu_sequence_tokens': CPU_LIMITS['sequence_tokens'],
        'generated_tokens': generated_token_ceiling(),
        'reference_device': 'Apple MPS remains the guided GPU evidence. A CPU probe does not qualify MPS, CUDA, ROCm, or XPU.',
        'qlora': 'unsupported_until_unquantized_comparison_passes',
        **commercial_status(),
    }


class CapabilityLedger(APIView):
    permission_classes = [IsAuthenticated, TenantRBAC]
    required_role = Role.VIEWER

    def get(self, request):
        response = Response(ledger_payload())
        response['Cache-Control'] = 'no-store'
        return response
