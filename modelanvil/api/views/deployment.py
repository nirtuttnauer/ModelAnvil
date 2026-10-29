"""Describe installed operations; each operation still enforces its own admission."""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from modelanvil.identity.models import Role, role_at_least
from modelanvil.runners.training import hf_runtime
from modelanvil.runners.training.managed import host_status


class DeploymentCapabilities(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        role = request.modelanvil_role
        engineer = role_at_least(role, Role.ENGINEER)
        host = host_status()
        reason = ('An engineer or administrator can launch training.' if not engineer else
                  host['message'] if not host['available'] else '')
        limits = {'max_rows': hf_runtime.LIMITS['rows'],
                  'max_tokens': hf_runtime.LIMITS['sequence_tokens'],
                  'max_steps': hf_runtime.LIMITS['steps'], 'max_cases': 64,
                  'max_output_tokens': 32}
        response = Response({
            'mode': 'local', 'role': role,
            'operations': {
                'classification': {'enabled': engineer and host['available'], 'reason': reason, 'limits': limits},
                'local_training': {'enabled': engineer and host['available'], 'reason': reason, 'limits': limits},
                'evaluation': {'enabled': engineer, 'reason': '' if engineer else 'An engineer can queue comparisons.',
                               'limits': {'max_cases': 64, 'max_output_tokens': 32}},
                'chat': {'enabled': engineer, 'reason': '' if engineer else 'An engineer can run inference.'},
                'model_export': {'enabled': True, 'reason': 'Exports require an accessible completed candidate.'},
                'team_management': {'enabled': role_at_least(role, Role.ADMIN),
                                    'reason': 'The installation owner provisions local workspace membership.'},
            },
            'readiness': {'training_enabled': host['available'], 'training_busy': host['busy'],
                          'qualification_scope': 'local-apple-beta', 'production_qualified': False},
        })
        response['Cache-Control'] = 'private, no-store'
        return response
