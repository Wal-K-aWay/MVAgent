"""Compare all three completed model panels without changing their scores."""
import json
from pathlib import Path

ROOTS = {'9B':'pro9_ffmpeg_20261016','27B':'pro9_ffmpeg_27b_20261016',
         '35B-A3B':'pro9_ffmpeg_35b_20261016'}


def read(path):
    return json.loads(path.read_text())


def main():
    inputs=None;source=None;selection=None;config=None;results={}
    for size,name in ROOTS.items():
        root=Path('/runs/devbox')/name
        assert read(root/'progress.json')['phase']=='completed',size
        current_inputs={j['sample_id']:j['inputs'] for j in read(root/'jobs.json')}
        current_source=read(root/'code/experiments/pro9_ffmpeg/source_provenance.json')['experiment_sha256']
        current_selection=read(root/'selection.json')
        current_config=read(root/'base_config.json')
        alias=next(iter(current_config['models']))
        current_config['models'][alias]['model_name']='<actor weights>'
        current_config=json.loads(json.dumps(current_config).replace(json.dumps(alias),'"<actor>"'))
        if inputs is None:
            inputs,source,selection,config=current_inputs,current_source,current_selection,current_config
        assert current_inputs==inputs and len(inputs)==330,size
        assert current_source==source and current_selection==selection and current_config==config,size
        closed=read(root/'analysis/closed_summary.json')
        opened=read(root/'analysis/ccqa_summary.json')
        checked=read(root/'analysis/final_checks.json')
        assert closed['completed_closed']==300 and closed['completed_total']==330
        assert not closed['actor_errors'] and checked['judge_rows']==120
        results[size]=dict(closed=closed['benchmarks'],ccqa=opened['arms'],
            crossvid_ten_task=opened['crossvid_ten_task_estimate'],
            diagnostics={key:checked[key] for key in ['timing','empty','brace_only','forced_answers',
                'questions_with_truncation','format_errors_by_answer_status']},
            calls=closed['calls'],truncations=closed['length_responses'],http_errors=closed['http_errors'],
            format_errors=len(checked['format_errors']),source=str(root))
    result=dict(models=results,common_questions=330,identical_legacy_source=True,
                identical_base_config_except_actor=True,
                caveat='Development panel; 9B used 16 workers, other models used 8; prior direct arm has no CCQA.')
    target=Path('/runs/devbox/pro9_ffmpeg_large_20261016/analysis/comparison.json')
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    for size,r in results.items():
        print(size,{k:v['arms']['restored']['score'] for k,v in r['closed'].items()},
              'CCQA',r['ccqa']['restored']['official_score'],'Cross10',r['crossvid_ten_task']['restored'],
              'format',r['format_errors'],'truncations',r['truncations'],flush=True)


if __name__=='__main__':main()
