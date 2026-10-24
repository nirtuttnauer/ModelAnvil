"""Bundled read-only MCP2025-11-25 arithmetic server; no arbitrary executors or I/O tools."""
import json
import math
import sys

VERSION='2025-11-25'
PARAMETERS={'type':'object','properties':{n:{'type':'integer','minimum':-1000000,'maximum':1000000} for n in ('a','b')},
    'required':['a','b'],'additionalProperties':False}
TOOLS=[{'name':name,'description':description,'inputSchema':PARAMETERS,
    'annotations':{'readOnlyHint':True,'destructiveHint':False,'openWorldHint':False}}
    for name,description in [('add','Add two bounded integers.'),('multiply','Multiply two bounded integers.')]]


def reply(identifier,*,result=None,error=None):
    value={'jsonrpc':'2.0','id':identifier}
    value['error' if error else 'result']=error if error else result
    print(json.dumps(value,allow_nan=False),flush=True)


def main():
    initialized=False;ready=False
    for _ in range(32):
        raw=sys.stdin.buffer.readline(65537)
        if not raw:return
        try:
            if len(raw)>65536:raise ValueError()
            request=json.loads(raw,parse_constant=lambda value:(_ for _ in ()).throw(ValueError()))
            if (not isinstance(request,dict) or request.get('jsonrpc')!='2.0' or set(request)-{'jsonrpc','id','method','params'}
                    or not isinstance(request.get('method'),str) or not isinstance(request.get('params',{}),dict)
                    or 'id' in request and (type(request['id']) is not int or not 0<=request['id']<=2147483647)):
                raise ValueError()
        except (ValueError,TypeError,RecursionError):
            reply(None,error={'code':-32700,'message':'Invalid bounded MCP request.'});continue
        method,params,identifier=request['method'],request.get('params',{}),request.get('id')
        if method=='notifications/initialized' and initialized and identifier is None:ready=True;continue
        if identifier is None:continue
        if method=='initialize' and not initialized and params.get('protocolVersion')==VERSION:
            initialized=True;reply(identifier,result={'protocolVersion':VERSION,'capabilities':{'tools':{'listChanged':False}},
                'serverInfo':{'name':'ModelAnvil bounded arithmetic','version':'1'}})
        elif method=='tools/list' and ready:
            reply(identifier,result={'tools':TOOLS})
        elif method=='tools/call' and ready:
            name,args=params.get('name'),params.get('arguments')
            if (name not in ('add','multiply') or not isinstance(args,dict) or set(args)!={'a','b'}
                    or any(type(v) is not int or abs(v)>1000000 for v in args.values())):
                reply(identifier,result={'content':[{'type':'text','text':'Unsupported tool or invalid arguments.'}],
                    'structuredContent':{'error':'invalid_tool_arguments'},'isError':True});continue
            value=args['a']+args['b'] if name=='add' else args['a']*args['b']
            result={'value':value}
            reply(identifier,result={'content':[{'type':'text','text':json.dumps(result)}],'structuredContent':result,'isError':False})
        else:reply(identifier,error={'code':-32601,'message':'Unsupported MCP method or protocol state.'})


if __name__=='__main__':main()
