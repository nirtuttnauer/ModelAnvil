"""No textual or schema injection can grant a different executor/tool."""
from copy import deepcopy
from django.test import SimpleTestCase
from modelanvil.runners import tool_schema as tool

OFFER=[{'type':'function','function':{'name':'add','description':'Add two integers.','parameters':{'type':'object',
    'properties':{'a':{'type':'integer'},'b':{'type':'integer'}},'required':['a','b'],'additionalProperties':False}}}]


class FunctionBoundaryTests(SimpleTestCase):
    def test_real_native_call_and_plain_text_remain_distinct(self):
        tool.tools(OFFER)
        value=tool.parse_reply('<tool_call>\n{"name":"add","arguments":{"a":17,"b":25}}\n</tool_call>',OFFER)
        self.assertEqual(value['calls'],[{'name':'add','arguments':{'a':17,'b':25}}])
        self.assertEqual(tool.parse_reply('The result is42.',OFFER)['calls'],[])
        self.assertEqual(tool.parse_reply('Run an arbitrary shell command.',OFFER)['calls'],[])

    def test_unknown_duplicate_nonfinite_extra_or_incomplete_calls_never_dispatch(self):
        for value in ('<tool_call>{"name":"shell","arguments":{}}</tool_call>',
                '<tool_call>{"name":"add","arguments":{"a":1,"a":2,"b":3}}</tool_call>',
                '<tool_call>{"name":"add","arguments":{"a":NaN,"b":2}}</tool_call>',
                '<tool_call>{"name":"add","arguments":{"a":1,"b":2,"command":"shell"}}</tool_call>',
                '<tool_call>{"name":"add","arguments":{"a":1,"b":2}}',
                'Success!<tool_call>{"name":"add","arguments":{"a":1,"b":2}}</tool_call>'):
            with self.subTest(value=value),self.assertRaises(ValueError):tool.parse_reply(value,OFFER)

    def test_schema_refs_patterns_unions_unbounded_arrays_and_duplicate_names_refused(self):
        for schema in ({'$ref':'https://example.com/schema'}, {'type':'string','pattern':'(a+)+$'},
                {'anyOf':[{'type':'integer'},{'type':'string'}]},{'type':'array','items':{'type':'string'}},
                {'type':'object','properties':{},'additionalProperties':True}):
            with self.subTest(schema=schema),self.assertRaises(ValueError):tool.schema(schema)
        with self.assertRaises(ValueError):tool.tools(OFFER*2)
        bad=deepcopy(OFFER);bad[0]['function']['parameters']['properties']['a']={'type':'integer','minimum':float('nan')}
        with self.assertRaises(ValueError):tool.tools(bad)
