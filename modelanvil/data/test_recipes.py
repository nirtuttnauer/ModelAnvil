"""Typed recipe validation and deterministic transforms never interpret code."""
import copy
from django.test import SimpleTestCase
from modelanvil.data import recipes


def definition():
    return {'schema':recipes.SCHEMA,'name':'Document notes','steps':[
        {'id':'source','type':'source','format':'json'},
        {'id':'sample','type':'sample','input':'source','limit':3,'seed':42},
        {'id':'clean','type':'expression','input':'sample','operation':'strip'},
        {'id':'output','type':'output','input':'clean'}]}


class RecipeKernelTests(SimpleTestCase):
    def test_cycles_duplicate_ids_and_executable_expressions_are_refused(self):
        recipes.validate_recipe(definition())
        bad=[]
        graph=definition();graph['steps'][1]['input']='output';bad.append(graph)
        graph=definition();graph['steps'][1]['id']='source';bad.append(graph)
        graph=definition();graph['steps'][2]['operation']='eval';bad.append(graph)
        graph=definition();graph['steps'][1]['limit']=True;bad.append(graph)
        graph=definition();graph['steps'][1]['seed']=float('nan');bad.append(graph)
        for graph in bad:
            with self.assertRaises(ValueError):recipes.validate_recipe(graph)

    def test_json_and_code_validation_does_not_execute_generated_code(self):
        self.assertEqual(recipes.parse_generated('{"status":"ok"}','json'),{'status':'ok'})
        self.assertEqual(recipes.parse_generated('raise RuntimeError("not executed")','code'),'raise RuntimeError("not executed")')
        for text,kind in [('{"a":1,"a":2}','json'),('{"x":NaN}','json'),('unfinished =','code'),('','text')]:
            with self.assertRaises(ValueError):recipes.parse_generated(text,kind)

    def test_template_substitution_is_literal_and_types_are_checked(self):
        cell={'key':'first','value':'literal {{source}}','format':'text','trace':[], 'usage':{},
            'source':{'blocks':[{'type':'text','text':'Original source'}]}}
        result=recipes.transform(cell,{'id':'prompt','type':'template','template':'Use {{value}} and {{source}}'})
        self.assertEqual(result['value'],'Use literal {{source}} and Original source')
        graph=definition();graph['steps'].insert(2,{'id':'generated','type':'generate','input':'sample','output':'json','max_tokens':32,'seed':42})
        graph['steps'][3]['input']='generated'
        with self.assertRaisesMessage(ValueError,'text only'):recipes.validate_recipe(graph)
