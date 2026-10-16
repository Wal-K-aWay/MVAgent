"""Run the released LensWalk evaluator; adapt input/transport, then score separately."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys
import time
import urllib.request

from common import sha256, write
from transport_audit import audit_httpx


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--item', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint', required=True)
    args = p.parse_args()
    if not (3,9) <= sys.version_info[:2] < (3,12):
        raise RuntimeError('LensWalk declares Python >=3.9,<3.12; use its isolated client environment')
    source, out = args.source.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    if (out/'result.json').exists():
        raise FileExistsError(out/'result.json')
    item = json.loads(args.item.read_text())
    with urllib.request.urlopen(args.endpoint.rstrip('/')+'/models', timeout=30) as response:
        card = json.load(response)['data'][0]
    if card['execution']['profile'] != 'qwen35-bf16-lenswalk-tools':
        raise RuntimeError('Expected the dedicated fixed Qwen tool-call service')
    write(out/'service_card.json',card)
    annotation = dict(id=item['sample_id'], video_path=item['video_path'], duration=item['duration'],
                      question=item['question'])
    # Prepared questions already contain their options; no labels enter the inference file.
    (out/'input.jsonl').write_text(json.dumps(annotation,ensure_ascii=False)+'\n')
    write(out/'effective_config.json',dict(upstream_commit='c3cdf13a6ffc6b1ce21af3a0c7813178d17fac77',
        python=sys.version, model=card['id'], max_turns=5, observer_temperature=.2,
        max_output_tokens=None, planner_temperature=None, subject_registry=False,
        limit_scan_calls=False, use_subtitle=False, max_edge_length=512,
        frame_budgets=dict(segment=32,scan=180,stitched=128),
        source_sha256={str(f.relative_to(source)):sha256(f) for f in sorted(source.rglob('*'))
                       if f.is_file() and f.suffix in ('.py','.yaml') and '__pycache__' not in f.parts},
        adaptations=['local Qwen endpoint and native tool-call parser', 'multi-video concatenation prompt',
                     'inference-only flag; official benchmark scoring follows saved raw answers']))
    os.environ.update(OPENAI_API_KEY='local-no-auth',OPENAI_BASE_URL=args.endpoint,
        TOOL_OPENAI_API_KEY='local-no-auth',TOOL_OPENAI_BASE_URL=args.endpoint,MLLM_BACKEND=card['id'])
    audit_httpx(out/'requests.jsonl')
    sys.path.insert(0,str(source))
    sys.argv=[str(source/'eval/infer_bench_summ_vcs.py'), '--model_name_or_path',card['id'],
        '--tool_config',str(source/'tool_configs/vcs_standard.yaml'), '--bench_name',str(out/'input.jsonl'),
        '--batch_size','1','--inference_only','True']
    os.chdir(out)
    started=time.monotonic()
    runpy.run_path(sys.argv[0],run_name='__main__')
    conversations=list(out.glob('results/run_lods/*/all_conversations.jsonl'))
    if len(conversations)!=1:
        raise RuntimeError(f'Expected one LensWalk output, found {len(conversations)}')
    rows=[json.loads(line) for line in conversations[0].read_text().splitlines()]
    assert len(rows)==1 and rows[0]['question']==item['question']
    calls=[json.loads(line) for line in (conversations[0].parent/'all_tool_calls.jsonl').read_text().splitlines()]
    visual=[r for r in calls if r['tool_name']!='finish']
    answer=rows[0]['answer']
    result=dict(sample_id=item['sample_id'], answer=answer, seconds=time.monotonic()-started,
        visual_tool_calls=len(visual), tool_errors=[r for r in visual if r['error']],
        finished_with_tool=any(r['tool_name']=='finish' for r in calls),
        transcript=str(conversations[0]))
    write(out/'result.json',result)
    print(json.dumps(result,ensure_ascii=False))
    if not isinstance(answer,str) or not answer.strip() or not any(not r['error'] for r in visual):
        raise RuntimeError('LensWalk did not return an answer grounded in a completed observation')


if __name__=='__main__':
    main()
