"""Use upstream MetaVideoAgent profiling, generated modules and execution runtime."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

from common import LocalQwen, sha256, write


def configure(source, output, client):
    profiles = json.loads((source/'configs/provider_profiles.openai_compatible.example.json').read_text())
    for profile in profiles['profiles']:
        profile['model_id'] = client.model
        profile['request_options'] = {'enable_thinking': False}
        if profile['capability'] in ('asr', 'embedding'):
            profile['enabled_by_default'] = False
    write(output/'profiles.json', profiles)
    os.environ.update(METAVIDEOAGENT_CAPABILITY_PROFILES=str(output/'profiles.json'),
        METAVIDEOAGENT_API_KEY='local-no-auth', METAVIDEOAGENT_BASE_URL=client.endpoint,
        METAVIDEOAGENT_RUNTIME_DIR=str(source/'execution/action_runtime'),
        METAVIDEOAGENT_LLM_PROFILE='custom.llm.reasoning',
        METAVIDEOAGENT_EVOLUTION_LLM_PROFILE='custom.llm.evolution',
        METAVIDEOAGENT_REVIEW_LLM_PROFILE='custom.llm.evolution',
        METAVIDEOAGENT_POST_DECISION_LLM_PROFILE='custom.llm.evolution',
        METAVIDEOAGENT_VLM_PROFILE='custom.vlm.default',
        METAVIDEOAGENT_ASR_PROFILE='custom.asr.default',
        METAVIDEOAGENT_OCR_PROFILE='custom.ocr.default',
        METAVIDEOAGENT_EMBEDDING_PROFILE='custom.embedding.default',
        METAVIDEOAGENT_PROVIDER_TIMEOUT_SEC='1860', LLM_MAX_RETRIES='1',
        VLM_MAX_RETRIES='1', METAVIDEOAGENT_VLM_MAX_CONCURRENCY='1',
        METAVIDEOAGENT_LLM_MAX_CONCURRENCY='1')
    for directory in (source, source/'evolution', source/'execution/action_runtime'):
        sys.path.insert(0, str(directory))
    import httpx
    import utils
    from openai import OpenAI

    def transport(request):
        if request.url.path.endswith('/embeddings'):
            raise RuntimeError('Embedding is unavailable in this visual-only initial profile')
        body = json.loads(request.content)
        response = client.chat(body['messages'], max_tokens=min(body.get('max_tokens') or 2048, 8192))
        return httpx.Response(200, json=response)

    def make_client(api_key, base_url, timeout=1860):
        return OpenAI(api_key='local-no-auth', base_url=client.endpoint, max_retries=0,
                      http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    utils.make_openai_client = make_client
    return utils


def generate(args, client):
    from channel_profile_runner import build_channel_profile
    from initial_combo_designer import design_initial_combo
    from initial_baseline_agent import build_initial_baseline_bundle
    items = json.loads(args.items.read_text())
    # This is a development smoke panel: three unlabeled questions also used in evaluation.
    selected = {}
    for item in items:
        selected.setdefault(item['sample_id'].split(':')[0], item)
    workspace = args.output/'workspace'
    (workspace/'raw_videos').mkdir(parents=True, exist_ok=True)
    rows = []
    for i, item in enumerate(selected.values()):
        video_id = f'profile_{i}'
        (workspace/'raw_videos'/f'{video_id}.mp4').symlink_to(item['video_path'])
        rows.append(dict(video_id=video_id, question=item['question'], choices=list(item['options'].values())))
    questions = args.output/'profile_questions.jsonl'
    questions.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    manifest = args.output/'distribution.json'
    write(manifest, dict(distribution_id='unlabeled_multivideo_development', splits={'train': str(questions)}))
    profile = build_channel_profile(str(workspace), str(manifest), str(args.output/'profile.json'),
        include_execution_artifacts=False, semantic_observer_mode='observe', semantic_video_budget=3,
        semantic_observe_workers=1, runtime_dir=str(args.source/'execution/action_runtime'),
        vlm_model=client.model)
    design_initial_combo(profile, str(manifest), str(args.output/'initial_combo_plan.json'))
    _, prompt = build_initial_baseline_bundle(str(workspace), str(manifest), profile,
        deep_research_summary='Visual-only benchmark inputs have no audio. ASR and embedding capabilities '
        'are unavailable. Use registered Qwen VLM/LLM/OCR and native persistent text evidence. '
        'Maintain each original video identity and timestamp offsets from the supplied question.',
        codegen_output_dir=str(args.output), execute_codegen=False)
    prompt += ('\nThe code author is now a local Qwen HTTP model. Return the canonical bundle JSON '
               'directly as your response instead of writing a filesystem file. All other ABI, '
               'five-module responsibilities and no-answer-supervision rules still apply.')
    (args.output/'codegen_prompt.txt').write_text(prompt)
    complete_bundle(args, client, [{'role': 'user', 'content': prompt}])


def complete_bundle(args, client, messages):
    from initial_baseline_agent import validate_bundle, _extract_json_object
    from sandbox_evaluator import preflight_bundle_runtime
    write(args.output/'codegen_messages.json', messages)
    for attempt in range(3):
        raw = client.chat(messages, max_tokens=8192, structured_outputs={'json': {'type':'object'}})
        text = raw['choices'][0]['message']['content']
        write(args.output/f'codegen_response_{attempt}.json', raw)
        try:
            bundle = _extract_json_object(text)
            bundle = bundle.get('initial_baseline_bundle', bundle)
            validation = validate_bundle(bundle)
            if not validation['passed']:
                raise ValueError(validation['issues'])
            write(args.output/f'bundle_attempt_{attempt}.json', bundle)
            validation = preflight_bundle_runtime(bundle)
            write(args.output/f'preflight_{attempt}.json', validation)
            if not validation['passed']:
                raise ValueError(validation)
            write(args.output/'bundle.json', bundle)
            print('Generated initial bundle passed upstream runtime preflight', flush=True)
            return
        except (ValueError, KeyError, TypeError) as exc:
            write(args.output/f'codegen_failure_{attempt}.json', {'error': str(exc)})
            messages.extend([{'role':'assistant','content':text}, {'role':'user','content':
                'Repair the complete bundle using the original ABI. Return only the complete bundle JSON. '
                'No answer labels are available. Host error: '+str(exc)}])
    raise RuntimeError('Qwen failed to generate a valid initial bundle after two repairs')


def repair(args, client):
    bundle = json.loads(args.bundle.read_text())
    failed = json.loads(args.failure.read_text())
    feedback = (json.dumps(failed['smoke_feedback']) if failed.get('smoke_feedback') else
                failed.get('traceback') or failed.get('error'))
    if not feedback:
        raise ValueError('Repair needs an observed runtime failure')
    write(args.output/'repair_provenance.json', dict(bundle=str(args.bundle),
        bundle_sha256=sha256(args.bundle), context_sha256=sha256(args.context),
        failure=str(args.failure), failure_sha256=sha256(args.failure)))
    complete_bundle(args, client, [
        {'role':'user', 'content':args.context.read_text()},
        {'role':'assistant', 'content':json.dumps(bundle)},
        {'role':'user', 'content':'The real initial-agent smoke failed with the traceback below. '
         'Repair the generated code against the exact base-method return types in the ABI witness. '
         'Keep unrelated strategies unchanged. Return the complete canonical bundle JSON only. '
         'No answer labels or evaluation scores are supplied.\n'+feedback}])


def infer(args):
    from agent import MetaVideoAgent
    import module_map
    from run_video_qa import VideoQAEnv, build_video_structure
    from sandbox_evaluator import (inject_module_bundle, run_single_question,
        behavioral_smoke_assessment, build_initial_smoke_failure_contract,
        build_engineering_smoke_execution_trace)
    bundle = json.loads(args.bundle.read_text())
    refs = dict(structuring=module_map.STRUCTURING_MAP, thinking=module_map.THINKING_MAP,
        memory=module_map.WORK_MEMORY_MAP, localization=module_map.LOCALIZATION_MAP,
        perception=module_map.PERCEPTION_MAP)
    ok, combo, configs, validation = inject_module_bundle(bundle, refs)
    if not ok:
        raise ValueError(validation)
    item = json.loads(args.item.read_text())
    video_id = item['sample_id'].replace(':','_')
    workspace = args.output/'workspace'
    (workspace/'raw_videos').mkdir(parents=True, exist_ok=True)
    (workspace/'raw_videos'/f'{video_id}.mp4').symlink_to(item['video_path'])
    configs['agent'] = dict(max_steps=10, llm_temperature=0, vlm_temperature=0, max_output_tokens=2048)
    started = time.monotonic()
    row = run_single_question(MetaVideoAgent, VideoQAEnv, build_video_structure,
        str(workspace), video_id, combo, {'question':item['question'], 'choices':list(item['options'].values())},
        str(args.output/'trace'), custom_configs=configs)
    row.update(sample_id=item['sample_id'], seconds=time.monotonic()-started,
               protocol='Qwen-generated initial bundle; no evolution')
    behavior = behavioral_smoke_assessment([row], combo)
    row['behavioral_smoke'] = behavior
    if not behavior['passed']:
        row['smoke_feedback'] = dict(behavior=behavior,
            failure_contract=build_initial_smoke_failure_contract([row], bundle),
            execution_trace=build_engineering_smoke_execution_trace([row]))
        row['error'] = row.get('error') or behavior['reason']
    write(args.output/'result.json', row)
    if row.get('error') or not str(row.get('answer') or '').strip():
        raise RuntimeError(row.get('error') or 'Empty MetaVideoAgent answer')
    print(json.dumps({k: row.get(k) for k in ('sample_id','answer','seconds','steps')}), flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=['generate','repair','infer'])
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--items', type=Path)
    p.add_argument('--item', type=Path)
    p.add_argument('--bundle', type=Path)
    p.add_argument('--context', type=Path)
    p.add_argument('--failure', type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    client = LocalQwen(args.endpoint, args.output/'requests.jsonl')
    configure(args.source, args.output, client)
    if args.mode == 'generate':
        generate(args, client)
    elif args.mode == 'repair':
        repair(args, client)
    else:
        infer(args)


if __name__ == '__main__':
    main()
