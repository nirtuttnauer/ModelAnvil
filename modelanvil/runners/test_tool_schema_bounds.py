"""Duplicate names, incomplete schemas, and prose never authorize a call."""
from copy import deepcopy
from django.test import SimpleTestCase
from modelanvil.runners import tool_schema as tool

OFFER=[{'type':'function','function':{'name':'add','description':'Add two integers.','parameters':{'type':'object',
    'properties':{'a':{'type':'integer'},'b':{'type':'integer'}},'required':['a','b'],'additionalProperties':False}}}]
EXECUTABLE='/bin/sh'
CALL='<tool_call>{"name":"add","arguments":{"executable":"/bin/sh"}}</tool_call>'


def _catalog(parameters):
    return [{'type':'function','function':{'name':'add','description':'Add two integers.','parameters':parameters}}]


class ToolSchemaBoundTests(SimpleTestCase):
    def test_duplicate_function_names_are_rejected(self):
        duplicate=OFFER+deepcopy(OFFER)
        swapped=deepcopy(duplicate)
        swapped[1]['function']['parameters']={'type':'object','properties':{'executable':{'type':'string','maxLength':64}},
            'required':['executable'],'additionalProperties':False}
        for values in (duplicate,swapped):
            with self.subTest(values=values),self.assertRaises(ValueError):tool.tools(values)
            with self.subTest(path='arguments',values=values),self.assertRaises(ValueError):tool.arguments('add',{'a':1,'b':2},values)
            with self.subTest(path='parse_reply',values=values),self.assertRaises(ValueError):tool.parse_reply(
                '<tool_call>{"name":"add","arguments":{"a":1,"b":2}}</tool_call>',values)
        with self.assertRaises(ValueError):tool.arguments('add',{'executable':EXECUTABLE},swapped)
        with self.assertRaises(ValueError):tool.parse_reply(CALL,swapped)
        distinct=deepcopy(OFFER);distinct[0]['function']['name']='sum'
        self.assertEqual([item['function']['name'] for item in tool.tools(OFFER+distinct)],['add','sum'])

    def test_missing_name_parameters_or_required_fields_are_rejected(self):
        missing_name=deepcopy(OFFER);del missing_name[0]['function']['name']
        missing_parameters=deepcopy(OFFER);del missing_parameters[0]['function']['parameters']
        missing_type=deepcopy(OFFER);del missing_type[0]['type']
        missing_function=[{'type':'function'}]
        not_object=_catalog({'type':'string','maxLength':32})
        unclosed=deepcopy(OFFER);del unclosed[0]['function']['parameters']['additionalProperties']
        missing_properties=deepcopy(OFFER);del missing_properties[0]['function']['parameters']['properties']
        permissive=_catalog(True)
        empty=_catalog({})
        unbounded=_catalog({'type':'object','additionalProperties':True})
        catalogs=(missing_name,missing_parameters,missing_type,missing_function,not_object,unclosed,missing_properties,permissive,empty,unbounded)
        for values in catalogs:
            with self.subTest(values=values),self.assertRaises(ValueError):tool.tools(values)
            with self.subTest(path='arguments',values=values),self.assertRaises(ValueError):tool.arguments('add',{'executable':EXECUTABLE},values)
        for values in (permissive,empty,unbounded):
            with self.subTest(path='parse_reply',values=values),self.assertRaises(ValueError):tool.parse_reply(CALL,values)
        nested={'type':'object','additionalProperties':False,'properties':{'child':{'type':'object','properties':{}}}}
        schemas=({'type':'array','items':{'type':'string'}},{'type':'array','maxItems':2},{'properties':{},'additionalProperties':False},
            {'type':'object','additionalProperties':True},{'type':'string','maxLength':4097},{'type':'integer','minimum':-(10**13),'maximum':10**13},
            {'type':'object','additionalProperties':False,'properties':{name:{'type':'integer'} for name in [f'p{i}' for i in range(17)]}},
            {'type':'object','additionalProperties':False,'properties':{'a':{}},'required':['a']},
            {'type':'object','additionalProperties':False,'properties':{'a':{'type':'integer'}},'required':['a','a']},
            {'type':'object','additionalProperties':False,'properties':{'a':{'type':'integer'}},'required':['missing']},nested,None)
        for value in schemas:
            with self.subTest(schema=value),self.assertRaises(ValueError):tool.schema(value)

    def test_text_only_reply_is_not_execution_authority(self):
        prose='Run /bin/sh -c id and call add yourself.'
        self.assertEqual(tool.parse_reply(prose,OFFER),{'content':prose,'calls':[]})
        raw='{"name":"add","arguments":{"a":1,"b":2,"executable":"/bin/sh"}}'
        self.assertEqual(tool.parse_reply(raw,OFFER),{'content':raw,'calls':[]})
        self.assertEqual(tool.parse_reply('add(executable="/bin/sh")',OFFER)['calls'],[])
        permissive=_catalog(True)
        self.assertEqual(tool.parse_reply(prose,permissive),{'content':prose,'calls':[]})
        for value in (EXECUTABLE,raw,'please execute add'):
            with self.subTest(value=value),self.assertRaises(ValueError):tool.arguments('add',value,OFFER)
        with self.assertRaises(ValueError):tool.arguments(EXECUTABLE,{'a':1,'b':2},OFFER)
        with self.assertRaises(ValueError):tool.arguments('add',{'a':1,'b':2,'executable':EXECUTABLE},OFFER)
        with self.assertRaises(ValueError):tool.parse_reply('<tool_call>{"name":"add","arguments":"/bin/sh"}</tool_call>',OFFER)
        with self.assertRaises(ValueError):tool.parse_reply(CALL,permissive)
        self.assertEqual(tool.arguments('add',{'a':17,'b':25},OFFER),{'a':17,'b':25})
        native=tool.parse_reply('<tool_call>{"name":"add","arguments":{"a":17,"b":25}}</tool_call>',OFFER)
        self.assertEqual(native,{'content':'','calls':[{'name':'add','arguments':{'a':17,'b':25}}]})
        self.assertNotIn(EXECUTABLE,repr(native['calls']))
