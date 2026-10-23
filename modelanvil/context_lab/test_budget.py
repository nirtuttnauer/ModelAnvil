"""Required text, explicit evidence omissions and final serialized budget invariants."""
from django.test import TestCase
from modelanvil.identity.models import Tenant
from modelanvil.core.tenancy import reset_context,set_active_tenant
from modelanvil.context_lab.models import ContextRecipe, ContextRecipeVersion, ContextBlockRevision
from modelanvil.context_lab.compiler import ContextCompiler, ContextOverflowError


class ContextBudgetTests(TestCase):
    def setUp(self):
        reset_context();self.tenant=Tenant.objects.create(slug='context-budget',name='Context budget')
        set_active_tenant(self.tenant.pk);self.addCleanup(reset_context)
        self.recipe=ContextRecipe.all_objects.create(tenant_id=self.tenant.pk,name='Budget')
        self.version=ContextRecipeVersion.all_objects.create(tenant_id=self.tenant.pk,recipe=self.recipe,
            model_limit_tokens=14,output_reserve_tokens=4,budget_policy='trim_optional_evidence')
    def block(self,key,text,priority=2,kind='evidence',**extra):
        return ContextBlockRevision.all_objects.create(tenant_id=self.tenant.pk,recipe_version=self.version,block_key=key,
            block_type=kind,role='user',order=self.version.blocks.count(),priority=priority,content_template=text,**extra)
    def compiler(self,**extra):
        return ContextCompiler(self.version,token_counter=len,serializer=lambda blocks:'|'.join(b.rendered_content for b in blocks)+'GEN',**extra)
    def test_empty_serialized_template_cannot_escape_final_budget_check(self):
        self.version.model_limit_tokens=5
        with self.assertRaises(ContextOverflowError):self.compiler().compile({})
        self.block('evidence','long evidence')
        with self.assertRaises(ContextOverflowError):self.compiler().compile({})
    def test_only_declared_optional_evidence_is_omitted(self):
        self.block('question','a',1,'user_query');self.block('history','h',10,'history');self.block('evidence','e'*40,2,max_tokens=8)
        result=self.compiler().compile({})
        self.assertEqual([b.block_key for b in result.included_blocks],['question','history'])
        self.assertEqual(result.omitted_blocks[0]['block_type'],'evidence')
        self.assertFalse(result.truncated_blocks[0]['included_in_final'])
        self.assertEqual(result.serialized_prompt,'a|hGEN')
        self.assertLessEqual(result.total_input_tokens+result.output_reserve_tokens,result.model_limit_tokens)
        with self.assertRaisesMessage(ContextOverflowError,'unselected categories'):
            self.compiler().compile({'history':'h'*50})
    def test_required_caps_fail_in_every_policy_and_optional_caps_are_explicit(self):
        block=self.block('required','required text',1,'instruction',max_tokens=3)
        for policy in ('fail_on_overflow','trim_lowest_priority','trim_optional_evidence'):
            self.version.budget_policy=policy
            with self.assertRaisesMessage(ContextOverflowError,'never truncated'):self.compiler().compile({})
        block.delete();self.block('evidence','abcdef',2,max_tokens=3)
        result=self.compiler().compile({})
        self.assertEqual(result.included_blocks[0].rendered_content,'abc')
        self.assertEqual(result.truncated_blocks[0]['tokens_retained'],3)
        self.assertFalse(result.truncated_blocks[0]['required'])
    def test_unknown_policy_and_a_limit_above_runtime_are_refused(self):
        with self.assertRaises(ContextOverflowError):self.compiler(runtime_limit_tokens=10).compile({})
        self.version.budget_policy='silently summarize'
        with self.assertRaisesMessage(ContextOverflowError,'Unknown overflow policy'):self.compiler().compile({})
