"""Remote CPU contract: native tool arguments, full answer strings and API defaults."""
from pathlib import Path
import sys

from transformers import AutoTokenizer
from vllm.tool_parsers import ToolParserManager

from lenswalk_server import request_of, input_digest, extraction_request

tokenizer=AutoTokenizer.from_pretrained('/weights/Qwen3.5-35B-A3B')
tool=dict(type='function',function=dict(name='finish',parameters=dict(type='object',
    properties={'answer':{'type':'string'}},required=['answer'])))
body=dict(model='local',messages=[dict(role='user',content='Return the requested answer.')],tools=[tool])
request=request_of(body,'local')
params=request.to_sampling_params(max_tokens=12345,default_sampling_params={})
assert params.max_tokens==12345 and params.temperature==1.0 and params.seed==0
assert request_of(dict(body,temperature=.2),'local').to_sampling_params(12345,{}).temperature==.2
assert input_digest(body)!=input_digest(dict(body,tools=[]))
for answer in ('AB','2->1->3','12.50,19.00','A natural-language answer.'):
    parser=ToolParserManager.get_tool_parser('qwen3_coder')(tokenizer,request.tools)
    parsed=parser.extract_tool_calls(f'<tool_call>\n<function=finish>\n<parameter=answer>\n{answer}\n</parameter>\n</function>\n</tool_call>',request)
    import json
    assert parsed.tools_called and json.loads(parsed.tool_calls[0].function.arguments)['answer'].strip()==answer
interval_schema={'type':'object',
    'properties':{'interval':{'$ref':'#/$defs/TimeInterval'},'query':{'type':'string'}},
    '$defs':{'TimeInterval':{'type':'object','properties':{
        'start_sec':{'type':'number'},'end_sec':{'type':'number'}}}}}
interval_tool=dict(type='function',function=dict(name='scan',parameters=interval_schema))
referenced=request_of(dict(body,tools=[interval_tool]),'local')
before=referenced.model_dump()
parser=ToolParserManager.get_tool_parser('qwen3_coder')(tokenizer,referenced.tools)
parsed=parser.extract_tool_calls('<tool_call>\n<function=scan>\n<parameter=interval>\n{"start_sec":0,"end_sec":6.58}\n</parameter>\n<parameter=query>\n{"keep":"string"}\n</parameter>\n</function>\n</tool_call>',extraction_request(referenced))
assert json.loads(parsed.tool_calls[0].function.arguments)=={'interval':{'start_sec':0,'end_sec':6.58},'query':'{"keep":"string"}'}
assert referenced.model_dump()==before
for bad in (dict(body,seed=1),dict(body,enable_thinking=True),dict(body,unknown=True)):
    try: request_of(bad,'local')
    except ValueError: pass
    else: raise AssertionError('Accepted unsupported inference configuration')
print('LensWalk native tool parser, open answers, defaults and request boundaries passed')
