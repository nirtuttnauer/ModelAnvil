from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import serializers
from modelanvil.identity.auth import TenantRBAC
from modelanvil.identity.models import Role
from modelanvil.runners.accelerator_support import inspect,report

class OperationSupport(APIView):
    permission_classes=[IsAuthenticated,TenantRBAC]
    required_role=Role.VIEWER
    def get(self,request):
        values=request.query_params
        if not values:result=report()
        else:
            if (set(values)-{'operation','device','precision','quantization','offload'} or any(len(values.getlist(k))!=1 for k in values)
                    or not values.get('operation') or not values.get('device')):
                raise serializers.ValidationError('Select operation and device; optional precision, quantization and offload are explicit.')
            offload=serializers.BooleanField().run_validation(values.get('offload',False))
            result=inspect(values['operation'],values['device'],precision=values.get('precision','fp32'),quantization=values.get('quantization','none'),offload=offload)
        response=Response(result);response['Cache-Control']='no-store';return response
