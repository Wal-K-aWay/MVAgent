"""LensWalk's tool-call API on the fixed, serial Qwen numerical backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import time

from models.vlm.local import sync_server as base

PROFILE = 'qwen35-bf16-lenswalk-tools'


def request_of(body, model):
    from vllm.entrypoints.openai.chat_completion.protocol import ChatCompletionRequest
    allowed = {'model', 'messages', 'tools', 'tool_choice', 'parallel_tool_calls', 'temperature',
               'top_p', 'max_tokens', 'max_completion_tokens', 'seed', 'stream',
               'response_format', 'enable_thinking', 'chat_template_kwargs'}
    if not isinstance(body, dict) or set(body)-allowed:
        raise ValueError('Unsupported request fields')
    if body.get('model') != model or not body.get('messages'):
        raise ValueError('Expected the served model and nonempty messages')
    if type(body.get('seed', 0)) is not int or body.get('seed', 0) != 0 or body.get('stream', False) or body.get('enable_thinking', False):
        raise ValueError('This service requires seed=0, stream=false and thinking=false')
    if body.get('chat_template_kwargs', {'enable_thinking': False}) != {'enable_thinking': False}:
        raise ValueError('Unsupported chat template overrides')
    if body.get('tool_choice', 'auto') not in ('auto', 'none'):
        raise ValueError('Only automatic or disabled tool calling is supported')
    value = {k:v for k,v in body.items() if k not in ('enable_thinking','chat_template_kwargs')}
    return ChatCompletionRequest(**dict(value, seed=0, chat_template_kwargs={'enable_thinking': False}))


def input_digest(body):
    return base.digest(dict(request=body, seed=0, enable_thinking=False, profile=PROFILE))


def extraction_request(request):
    # vLLM's XML parser needs explicit types; keep the original schemas in the prompt.
    parsed = request.model_copy(deep=True)
    for tool in parsed.tools or []:
        parameters = tool.function.parameters
        for field in parameters.get('properties', {}).values():
            if '$ref' in field:
                reference = field['$ref']
                if not reference.startswith('#/'):
                    raise ValueError('Tool parameter references must be local')
                target = parameters
                for key in reference[2:].split('/'):
                    target = target[key.replace('~1', '/').replace('~0', '~')]
                field.update(target)
    return parsed


def configure():
    if base.PROFILE == PROFILE:
        return base
    original_profile = base.execution_profile
    def profile():
        return dict(original_profile(), lenswalk_transport_sha256=base.sha256_file(Path(__file__)),
            generation_policy='Preserve upstream explicit parameters; omitted sampling fields use standard vLLM OpenAI defaults; omitted output limit uses remaining context.',
            tool_parser='qwen3_coder', request_timeout_seconds=600)
    base.PROFILE = PROFILE
    base.ENGINE_CONFIG = dict(base.ENGINE_CONFIG, limit_mm_per_prompt={'image':512, 'video':8})
    base.REQUEST_TIMEOUT_SECONDS = 600
    base.execution_profile = profile
    base.validate_request = request_of
    base.input_digest = input_digest
    base.Engine = Engine
    return base


def validate_card(card):
    configure().validate_card(card)
    if card['execution'].get('lenswalk_transport_sha256') != base.sha256_file(Path(__file__)):
        raise RuntimeError('LensWalk transport differs from the serving source')


class Engine(base.Engine):
    def complete(self, body, wire):
        from vllm import RequestOutput
        from vllm.renderers.params import ChatParams
        from vllm.tool_parsers import ToolParserManager
        request = request_of(body, self.card['id'])
        parser = ToolParserManager.get_tool_parser('qwen3_coder')(self.llm.get_tokenizer(), request.tools)
        request = parser.adjust_request(request)
        tools = [tool.model_dump() for tool in request.tools] if request.tools and request.tool_choice != 'none' else None
        self.forward_calls = 0
        started = time.monotonic()
        signal.alarm(base.REQUEST_TIMEOUT_SECONDS)
        try:
            chat = ChatParams(chat_template_kwargs=dict(enable_thinking=False, tools=tools,
                add_generation_prompt=True, continue_final_message=False, tokenize=False))
            _, prompts = self.llm.renderer.render_chat([request.messages], chat,
                self.llm.renderer.default_chat_tok_params, prompt_extras={'mm_processor_kwargs':None})
            remaining = base.ENGINE_CONFIG['max_model_len']-len(prompts[0]['prompt_token_ids'])
            if remaining <= 0:
                raise ValueError('Input exceeds the model context')
            requested = request.max_completion_tokens if request.max_completion_tokens is not None else request.max_tokens
            params = request.to_sampling_params(max_tokens=min(remaining, requested) if requested is not None else remaining,
                                                default_sampling_params={})
            output = self.llm._render_and_run_requests(iter(prompts), [params], RequestOutput, use_tqdm=False)[0]
        finally:
            signal.alarm(0)
        if self.forward_calls <= 0:
            raise RuntimeError('No real model forward was observed')
        generated = output.outputs[0]
        parsed = parser.extract_tool_calls(generated.text, extraction_request(request)) if tools else None
        message = dict(role='assistant', content=parsed.content if parsed else generated.text)
        if parsed and parsed.tools_called:
            message['tool_calls'] = [call.model_dump() for call in parsed.tool_calls]
        generation = {k:getattr(params,k) for k in ('temperature','top_p','top_k','max_tokens','seed','skip_special_tokens')}
        usage = dict(prompt_tokens=len(output.prompt_token_ids), completion_tokens=len(generated.token_ids),
                     total_tokens=len(output.prompt_token_ids)+len(generated.token_ids),
                     prompt_tokens_details={'cached_tokens':output.num_cached_tokens})
        audit = dict(request_sha256=hashlib.sha256(wire).hexdigest(), input_sha256=input_digest(body),
            prompt_token_ids_sha256=base.digest(output.prompt_token_ids),
            worker={**self.worker,'forward_calls':self.forward_calls}, inference_seconds=time.monotonic()-started,
            cache_hit_rate=base.cache_hit_rate(usage))
        response = dict(id=f'chatcmpl-{os.getpid()}-{output.request_id}', object='chat.completion',
            created=int(time.time()), model=self.card['id'], prompt_token_ids=list(output.prompt_token_ids),
            choices=[dict(index=0,message=message,token_ids=list(generated.token_ids),
                finish_reason='tool_calls' if parsed and parsed.tools_called and generated.finish_reason=='stop' else generated.finish_reason)],
            usage=usage,audit=audit,raw_output=generated.text)
        with (self.log_dir/'requests.jsonl').open('a') as stream:
            stream.write(json.dumps(dict(id=response['id'], generation=generation, usage=usage, **audit,
                raw_output=generated.text, token_ids=list(generated.token_ids), finish_reason=generated.finish_reason))+'\n')
        return response


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--port', type=int, default=8100)
    p.add_argument('--log-dir', type=Path, required=True)
    args = p.parse_args()
    try:
        configure().serve(args.model,args.port,args.log_dir,'qwen3.5-35b-a3b')
    except KeyboardInterrupt:
        pass
