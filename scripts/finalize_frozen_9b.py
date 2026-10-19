"""Finish the frozen 9B Judge and export AgentCVR-shaped result files on Modal."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import gzip
import hashlib
import math
import re
import tarfile
import threading
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from run_full_e2e import now, read, write, sha

SOURCE = Path(__file__).resolve().parents[1]
RUN = Path('/runs/devbox/frozen_full_final_20261019')
OUT = Path('/runs/devbox/frozen_9b_results_20261019')
REPORT = 'score/ccqa_scores_official_qwen3_30b_a3b.json'


def judge():
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT/'judge_complete.json').exists(), 'Judge already completed'
    frozen = OUT/'judge_source'
    frozen.mkdir()
    names = ['eval/agent_eval/serve_ccqa_judge.sh', 'eval/agent_eval/score_crossvid_ccqa.py',
             'scripts/finalize_frozen_9b.py']
    for name in names:
        dest = frozen/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SOURCE/name, dest)
    manifest = read(RUN/'manifest.json')
    score_source = 'eval/agent_eval/score_crossvid_ccqa.py'
    assert sha(SOURCE/score_source) == manifest['actor_hashes'][score_source]
    write(OUT/'judge_manifest.json', dict(at=now(), root=str(RUN), model='Qwen3-30B-A3B-Instruct-2507',
        source_hashes={name:sha(frozen/name) for name in names},
        hardware=subprocess.check_output(['nvidia-smi','--query-gpu=index,name,uuid','--format=csv,noheader'],text=True),
        policy='Keep the prior 50 judgments. Score only the 189 newly completed CCQA answers; cache in the canonical shard dirs so later controllers reuse them.'))
    os.environ['JUDGE_LOG_DIR'] = str(OUT/'judge_servers')
    try:
        write(OUT/'progress.json', dict(phase='judge_loading', at=now()))
        subprocess.run(['bash', frozen/'eval/agent_eval/serve_ccqa_judge.sh', '0-3', '8400'], check=True)
        counts = []
        selection = read(RUN/'selection.json')
        for i, ids in enumerate(selection['partitions']):
            target = RUN/f'shard{i}/9B'
            expected = {int(s.rsplit(':',1)[1]) for s in ids if s.startswith('crossvid:CCQA:')}
            write(OUT/'progress.json', dict(phase='judging', shard=i, expected=len(expected), at=now()))
            subprocess.run([sys.executable, frozen/score_source, '--output', target, '--endpoints', '8400-8403'], check=True)
            result = read(target/REPORT)
            assert not result['failed_ids'] and {r['id'] for r in result['samples']}==expected
            assert all(r['status']=='ok' for r in result['samples'])
            write(OUT/f'judge/shard{i}.json',result)
            counts.append(len(expected))
        assert sum(counts)==189
        write(OUT/'judge_complete.json',dict(at=now(), new_judged=189, prior_judged=50, shards=counts))
        write(OUT/'progress.json',dict(phase='judge_completed',at=now(),new_judged=189))
    except BaseException:
        write(OUT/'progress.json',dict(phase='failed',at=now(),error=traceback.format_exc()))
        raise


MEDIA = re.compile(r'data:(?:image|video|audio)/[^;,\s]+;base64,[A-Za-z0-9+/=]+')
TOKEN_ARRAYS = {'token_ids', 'prompt_token_ids', 'completion_token_ids'}
EVENTS = {'model_request', 'model_response', 'model_error', 'structured_parsed',
          'structured_invalid', 'structured_repair', 'media_clip_profile', 'video_sampling'}


def text_trace(value):
    """Retain text and media fingerprints, excluding binary media and token arrays."""
    if isinstance(value, dict):
        return {k:text_trace(v) for k,v in value.items() if k not in TOKEN_ARRAYS}
    if isinstance(value, list):
        return [text_trace(v) for v in value]
    if isinstance(value, str):
        return MEDIA.sub(lambda m:'[media omitted; sha256='+hashlib.sha256(m[0].encode()).hexdigest()+']', value)
    return value


def self_check():
    source={'answer':' A ', 'token_ids':[1,2], 'request_sha256':'abc',
            'messages':[{'text':'Observe the car', 'url':'data:video/mp4;base64,YWJjZA=='}]}
    result=text_trace(source)
    assert result['answer']==' A ' and result['request_sha256']=='abc'
    assert 'token_ids' not in result and result['messages'][0]['text']=='Observe the car'
    assert '[media omitted; sha256=' in result['messages'][0]['url']
    assert not MEDIA.search(json.dumps(result)) and source['token_ids']==[1,2]


def export():
    self_check()
    assert read(OUT/'judge_complete.json')['new_judged']==189
    files=OUT/'files'
    assert not files.exists(), 'Never overwrite a verified package'
    files.mkdir()
    comparison_root=Path('/runs/devbox/frozen_full_9b_comparison_raw_20261019')
    paired=read(comparison_root/'paired.json')
    base={r['sample_id']:r for r in read(RUN/'baseline.json')['9B']}
    selection=read(RUN/'selection.json')
    expected={'cvbench':997,'mvu_eval':1824,'crossvid':2500}
    assert len(paired)==len({r['sample_id'] for r in paired})==5321
    old_recovery=Path('/runs/devbox/frozen_full_recovery_20261019')
    expected_sha={sid:r['sha256'] for sid,r in base.items()}
    for root in [RUN,old_recovery]:
        expected_sha.update({r['sample_id']:r['sha256'] for r in read(root/'inheritance.json')['inherited'] if r['model']=='9B'})
    smoke=read(old_recovery/'analysis/recovery_smoke.json')
    expected_sha['mvu_eval:TR:1416']=smoke['new_sha256']
    assert set(expected_sha)==set(selection['ids'])
    truth={f"cvbench:{r['id']}":r['answer'] for r in read(Path('/assets/cvbench/QAs.json'))}
    truth.update({f"mvu_eval:{r['task']}:{r['id']}":r['answer'] for r in read(Path('/assets/mvu-eval/QAs.json'))})
    for path in sorted(Path('/assets/crossvid/QA').glob('*.json')):
        for r in read(path):
            truth[f"crossvid:{path.stem}:{r['id']}"]=(dict(answer=r['answer'],scoring_points=r['scoring_points']) if path.stem=='CCQA' else r['answer'])
    archive_lock=threading.Lock()
    provenance=[]
    judge_rows={}
    with ExitStack() as stack:
        archives={}
        def archive_bytes(path,member):
            with archive_lock:
                if path not in archives:
                    archives[path]=stack.enter_context(tarfile.open(path))
                return archives[path].extractfile(member).read()
        # Reuse the original coverage/correctness arrays for the previously judged panel.
        reports={}
        for sid,row in base.items():
            if not sid.startswith('crossvid:CCQA:'): continue
            path=Path(row['path']).parents[3]/REPORT
            if str(path) not in reports:
                if path.exists(): report=read(path)
                else:
                    ref=row['provenance']
                    report=json.loads(archive_bytes(ref['archive'],'9B/'+REPORT))
                assert not report['failed_ids']
                reports[str(path)]={r['id']:r for r in report['samples']}
            result=reports[str(path)][int(sid.rsplit(':',1)[1])]
            assert result['prediction']==row['arms']['direct']['prediction'].strip()
            assert abs(result['score']/(2*len(result['coverage']))-row['arms']['direct']['score'])<1e-9
            judge_rows[sid]=result
        assert len(judge_rows)==50
        for i in range(2):
            for row in read(OUT/f'judge/shard{i}.json')['samples']:
                sid=f"crossvid:CCQA:{row['id']}"
                assert sid not in judge_rows
                judge_rows[sid]=row
        assert len(judge_rows)==239 and all(r['status']=='ok' for r in judge_rows.values())
        for row in paired:
            sid=row['sample_id']
            if sid in judge_rows:
                j=judge_rows[sid]
                assert j['prediction']==row['agent']['prediction'].strip()
                assert len(j['coverage'])==len(j['correctness'])==len(truth[sid]['scoring_points'])
                row['agent']['score']=j['score']/(2*len(j['coverage']))
        def convert(row):
            sid=row['sample_id']
            ref=base[sid]['provenance'] if sid in base else dict(path=row['path'])
            if 'archive' in ref: data=archive_bytes(ref['archive'],ref['member'])
            else: data=Path(ref['path']).read_bytes()
            digest=hashlib.sha256(data).hexdigest()
            assert digest==expected_sha[sid], sid
            raw=json.loads(data)
            assert raw['status']=='ok' and raw['sample_id']==sid
            result=raw['result']
            answer=result['answer']['answer']
            assert isinstance(answer,str) and answer.strip()==row['agent']['prediction']
            assert math.isfinite(result['time']) and result['time']>=0
            trace=dict(status=raw['status'],error=raw.get('error',''),attempt=raw.get('attempt'),
                result=text_trace(result),
                events=[text_trace(e) for e in raw['events'] if e['kind'] in EVENTS])
            line=dict(id=sid,gt=truth[sid],output=answer,seconds=result['time'],trajectory=trace)
            assert len(trace['result']['trajectory'])==len(result['trajectory'])
            assert sum(e['kind']=='model_response' for e in trace['events'])==row['stats']['calls']
            encoded=json.dumps(line,ensure_ascii=False,separators=(',',':'))+'\n'
            assert not MEDIA.search(encoded)
            return row['dataset'], encoded, {**ref,'id':sid,'sha256':digest}
        handles={ds:stack.enter_context((files/f'{ds}.jsonl').open('w')) for ds in expected}
        ordered=sorted(paired,key=lambda r:r['sample_id'])
        counts=Counter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            for start in range(0,len(ordered),64):
                for ds,line,ref in pool.map(convert,ordered[start:start+64]):
                    handles[ds].write(line);provenance.append(ref);counts[ds]+=1
                if start%512==0: print('EXPORTED',sum(counts.values()),now(),flush=True)
        assert counts==expected
    with (files/'ccqa_scores.jsonl').open('w') as stream:
        for sid,j in sorted(judge_rows.items()):
            item=dict(id=sid,score=j['score']/(2*len(j['coverage'])),points=len(j['coverage']),
                coverage=j['coverage'],correctness=j['correctness'],status=j['status'],judge_model='Qwen3-30B-A3B-Instruct-2507')
            stream.write(json.dumps(item,ensure_ascii=False,separators=(',',':'))+'\n')
    sys.path.insert(0,str(SOURCE/'scripts'))
    from run_full_mvagent import score
    scored=[dict(r,arms=dict(agent=r['agent'],e2e=r['e2e'])) for r in paired]
    summary={ds:dict(n=expected[ds],agent=score([r for r in scored if r['dataset']==ds],'agent'),
        e2e=score([r for r in scored if r['dataset']==ds],'e2e'),
        seconds=sum(r['stats']['seconds'] for r in paired if r['dataset']==ds)/expected[ds]) for ds in expected}
    lines=['# MVAgent Qwen3.5-9B：最终答案与文本轨迹','',
        '| Benchmark | 题数 | MVAgent得分（%） | 同题E2E（%） | 差值（pp） | 平均每题用时（秒） |',
        '|---|---:|---:|---:|---:|---:|']
    for ds,s in summary.items():
        lines.append(f"| {ds} | {s['n']} | {s['agent']*100:.2f} | {s['e2e']*100:.2f} | {(s['agent']-s['e2e'])*100:+.2f} | {s['seconds']:.2f} |")
    lines += ['', '所有5321题推理成功，239条CCQA均已评分；0空答案、0仅右花括号。',
        'CV/MVU按题平均；CrossVid十任务等权macro，CCQA按评分点加权。',
        'MVU E2E用官方指令移后；CV双方采用已有YES/NO选项映射，原E2E发布表62.09%，统一映射后62.49%。',
        '包含1500条复用开发题与3821条补测，不能称为独立Test。', '',
        '## 文件与字段', '',
        '`cvbench.jsonl`、`mvu_eval.jsonl`、`crossvid.jsonl`每行：',
        '- `id`：完整题号；`gt`：原始数据集答案，CCQA为原参考答案及评分点。',
        '- `output`：Engine最终answer字段的字符串原值，不strip、不重写或纠正格式。',
        '- `seconds`：已保存的整题耗时，不是并行墙钟时间，不含排队、模型加载及Judge。',
        '- `trajectory`：完整Engine结果及动作轨迹，模型请求文本、响应原文、解析/修复错误、媒体区间记录。',
        '`ccqa_scores.jsonl`沿用AgentCVR字段：id/score/points/coverage/correctness/status/judge_model。',
        '图片/视频Base64替换为SHA占位符，删除完整token ID数组和重复的传输/调度日志；保留文本与调用哈希、usage和执行状态。',
        '完整原始token、媒体请求、所有旧失败与冻结运行环境仍在Modal，不在本包中。', '',
        '## 来源', '',f'导出根：`{OUT}`；完整输入映射、逐文件SHA与原件SHA见根目录manifest.json。',
        f'原始运行：`{RUN}`，按baseline/inheritance保留各自源快照。',
        '固定BF16/8个独立H100 TP1 DP1 C1、seed0、temperature0、FlashInfer GDN、prefix/MM cache关闭。',
        '9B主要源677444b；单帧TR1416采用a0150f7补帧恢复；旧1500面板沿用e0ace27对应协议。',
        'Judge沿用Qwen3-30B-A3B-Instruct-2507及原官方Prompt/生成设置；旧50评分保留，新189缓存到原分片。']
    (files/'statistics.md').write_text('\n'.join(lines)+'\n')
    write(OUT/'comparison.json',dict(at=now(),complete=True,benchmarks=summary,ccqa_judged=239))
    write(OUT/'paired_scored.json',paired)
    entries=[dict(name=p.name,bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(files.iterdir())]
    archive=OUT/'mvagent-9b-results-with-trajectories-20261019.tar.gz'
    with archive.open('wb') as handle,gzip.GzipFile(filename='',fileobj=handle,mode='wb',compresslevel=1,mtime=0) as compressed,tarfile.open(fileobj=compressed,mode='w|') as pack:
        for entry in entries: pack.add(files/entry['name'],arcname=entry['name'])
    write(OUT/'manifest.json',dict(at=now(),samples=5321,counts=expected,ccqa=239,source_sha256=sha(Path(__file__)),
        files=entries,archive=dict(name=archive.name,bytes=archive.stat().st_size,sha256=sha(archive)),
        raw_sources=provenance,judge_manifest_sha256=sha(OUT/'judge_manifest.json'),comparison=summary))
    print(json.dumps(dict(comparison=summary,files=entries,archive_bytes=archive.stat().st_size)),flush=True)


def verify():
    manifest=read(OUT/'manifest.json')
    entries={e['name']:e for e in manifest['files']}
    seen=set()
    with tarfile.open(OUT/manifest['archive']['name'],'r:gz') as archive:
        for member in archive:
            assert member.name in entries and member.isfile()
            digest=hashlib.sha256();size=0;ids=set()
            with archive.extractfile(member) as stream:
                for line in stream:
                    digest.update(line);size+=len(line)
                    if member.name.endswith('.jsonl'):
                        row=json.loads(line);assert row['id'] not in ids;ids.add(row['id'])
                        if member.name!='ccqa_scores.jsonl':
                            assert set(row)=={'id','gt','output','seconds','trajectory'}
                            assert isinstance(row['output'],str) and row['output'].strip()
                            assert row['trajectory']['status']=='ok'
                            assert not MEDIA.search(line.decode())
            assert size==entries[member.name]['bytes'] and digest.hexdigest()==entries[member.name]['sha256']
            if ids:
                expected=239 if member.name=='ccqa_scores.jsonl' else manifest['counts'][member.name.removesuffix('.jsonl')]
                assert len(ids)==expected
            seen.add(member.name)
    assert seen==set(entries) and len(seen)==5
    assert sha(OUT/manifest['archive']['name'])==manifest['archive']['sha256']
    write(OUT/'verified.json',dict(at=now(),samples=5321,ccqa=239,files=5,archive=manifest['archive']))
    write(OUT/'progress.json',dict(phase='completed',at=now(),samples=5321,ccqa=239,files=5))
    print(json.dumps(read(OUT/'verified.json')),flush=True)


def complete():
    """Dev-box-only owner for CPU export after the independent Judge releases its GPUs."""
    import fcntl
    import time
    import modal
    here=Path('/tmp/mvagent-9b-results-20261019')
    lock=(here/'complete.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    volume=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')
    state=Path.home()/'wxu-evolve-agent/devbox/state-mvagent-frozen-9b-judge-20261019.json'
    owner=int((here/'controller.pid').read_text())
    while True:
        try:
            finished=json.loads(b''.join(volume.read_file('devbox/frozen_9b_results_20261019/judge_complete.json')))
        except FileNotFoundError:
            finished=None
        if finished is not None and not state.exists():
            assert finished['new_judged']==189
            break
        os.kill(owner,0)
        print(now(), 'waiting_for_judge_and_gpu_release',flush=True)
        time.sleep(45)
    sys.path.insert(0,str(Path.home()/'wxu-evolve-agent/devbox'))
    import frozen_9b_results_cpu as cpu
    with cpu.app.run(environment_name='zheng-dev'):
        rc,out,err=cpu.job.remote('python scripts/finalize_frozen_9b.py self-check && python scripts/finalize_frozen_9b.py export && python scripts/finalize_frozen_9b.py verify')
    print(out,err,flush=True)
    assert rc==0,rc
    print('PACKAGE_VERIFIED',now(),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['judge','export','verify','self-check','complete'])
    globals()[parser.parse_args().mode.replace('-','_')]()
