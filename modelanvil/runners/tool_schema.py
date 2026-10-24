"""Bounded function schemas and native tool-call parsing; no execution authority from text."""
import json
import math
import re
from jsonschema import Draft202012Validator,ValidationError,SchemaError

NAME=re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,47}$')


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON keys are not supported.')
        result[key]=value
    return result


def _constant(value):raise ValueError('Tool values must be finite JSON.')


def loads(raw):
    try:return json.loads(raw,object_pairs_hook=_unique,parse_constant=_constant)
    except (ValueError,TypeError,RecursionError):raise ValueError('Tool arguments require unique-key finite JSON.') from None


def bounded(value,depth=0):
    if depth>6:raise ValueError('Tool values exceed the bounded nesting limit.')
    if value is None or type(value) is bool:return
    if type(value) is int:
        if abs(value)>2**53-1:raise ValueError('Tool integer exceeds the safe JSON range.')
    elif type(value) is float:
        if not math.isfinite(value) or abs(value)>10**12:raise ValueError('Tool number exceeds its finite bound.')
    elif isinstance(value,str):
        if len(value)>4096 or len(value.encode())>16384:raise ValueError('Tool string exceeds its bound.')
    elif isinstance(value,list):
        if len(value)>16:raise ValueError('Tool array exceeds its bound.')
        for item in value:bounded(item,depth+1)
    elif isinstance(value,dict):
        if len(value)>16 or any(not isinstance(k,str) or len(k)>128 for k in value):raise ValueError('Tool object exceeds its bound.')
        for item in value.values():bounded(item,depth+1)
    else:raise ValueError('Tool values require ordinary JSON types.')


def schema(value,depth=0):
    if not isinstance(value,dict) or depth>4:raise ValueError('Tool schemas require bounded typed objects.')
    kind=value.get('type');common={'type','description','title','enum'}
    if kind=='object':
        if set(value)-common-{'properties','required','additionalProperties'} or value.get('additionalProperties') is not False:
            raise ValueError('Object schemas must disable additional properties; refs/composition/patterns are unsupported.')
        properties=value.get('properties');required=value.get('required',[])
        if (not isinstance(properties,dict) or len(properties)>16 or any(not isinstance(n,str) or not NAME.fullmatch(n) for n in properties)
                or not isinstance(required,list) or any(not isinstance(n,str) for n in required) or len(set(required))!=len(required) or any(n not in properties for n in required)):
            raise ValueError('Tool object properties and required names are invalid.')
        for item in properties.values():schema(item,depth+1)
    elif kind=='array':
        if (set(value)-common-{'items','minItems','maxItems'} or type(value.get('maxItems')) is not int
                or not 0<=value['maxItems']<=16):raise ValueError('Array schemas require at most16 items and a supported item schema.')
        schema(value.get('items'),depth+1)
    elif kind=='string':
        if set(value)-common-{'minLength','maxLength'} or type(value.get('maxLength',4096)) is not int or not 0<=value.get('maxLength',4096)<=4096:
            raise ValueError('String schemas exceed the supported bounded subset.')
    elif kind in ('integer','number'):
        if set(value)-common-{'minimum','maximum'} or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>10**12 for k,v in value.items() if k in ('minimum','maximum')):
            raise ValueError('Numeric schemas require finite bounded ranges.')
    elif kind in ('boolean','null'):
        if set(value)-common:raise ValueError('Boolean/null schema contains unsupported keywords.')
    else:raise ValueError('Use one supported explicit JSONSchema type; refs and unions require separate qualification.')
    for field,maximum in (('description',512),('title',128)):
        if field in value and (not isinstance(value[field],str) or len(value[field])>maximum):raise ValueError('Schema documentation exceeds its bound.')
    if 'enum' in value:
        if not isinstance(value['enum'],list) or not 1<=len(value['enum'])<=16:raise ValueError('Tool enum exceeds its bound.')
        bounded(value['enum'])
    try:Draft202012Validator.check_schema(value)
    except (SchemaError,TypeError,RecursionError):raise ValueError('Tool JSONSchema is malformed.') from None
    return value


def tools(values):
    if not isinstance(values,list) or not 0<=len(values)<=8:raise ValueError('Offer at most8 explicit function tools.')
    try:raw=json.dumps(values,allow_nan=False).encode()
    except (ValueError,TypeError,RecursionError):raise ValueError('Tool descriptors require finite JSON.') from None
    if len(raw)>32768:raise ValueError('Tool descriptors exceed32KiB.')
    seen=set()
    for value in values:
        if not isinstance(value,dict) or set(value)!={'type','function'} or value['type']!='function':raise ValueError('Only typed function tool descriptors are supported.')
        function=value['function']
        if (not isinstance(function,dict) or set(function)-{'name','description','parameters','strict'}
                or not isinstance(function.get('name'),str) or not NAME.fullmatch(function['name']) or function['name'] in seen
                or not isinstance(function.get('description',''),str) or len(function.get('description',''))>512
                or 'strict' in function and type(function['strict']) is not bool):raise ValueError('Tool names and descriptors must be unique and bounded.')
        seen.add(function['name']);schema(function.get('parameters'))
        if function['parameters']['type']!='object':raise ValueError('Function parameters require an object schema.')
    return values


def arguments(name,value,offered):
    allowed={t['function']['name']:t['function']['parameters'] for t in offered}
    if name not in allowed or not isinstance(value,dict):raise ValueError('The model selected an unoffered tool or invalid arguments.')
    bounded(value)
    try:Draft202012Validator(allowed[name]).validate(value)
    except (ValidationError,TypeError,RecursionError):raise ValueError('Tool arguments do not match the offered schema.') from None
    return value


def parse_reply(text,offered):
    if not isinstance(text,str) or len(text.encode())>16384:raise ValueError('Model tool response exceeds its bound.')
    if '<tool_call>' not in text and '</tool_call>' not in text:return {'content':text,'calls':[]}
    matches=list(re.finditer(r'<tool_call>\s*(\{.*?\})\s*</tool_call>',text,re.S))
    if not 1<=len(matches)<=2 or re.sub(r'<tool_call>\s*\{.*?\}\s*</tool_call>','',text,flags=re.S).strip():
        raise ValueError('Tool output must contain1–2 complete native call blocks without surrounding prose.')
    calls=[]
    for match in matches:
        value=loads(match.group(1))
        if not isinstance(value,dict) or set(value)!={'name','arguments'} or not isinstance(value['name'],str):raise ValueError('Native tool call schema is invalid.')
        arguments(value['name'],value['arguments'],offered);calls.append(value)
    return {'content':'','calls':calls}
