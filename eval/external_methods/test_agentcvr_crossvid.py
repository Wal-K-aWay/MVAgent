"""CPU checks for native CrossVid input boundaries and scoring, run on Modal."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

from agentcvr_crossvid import COUNTS, UPSTREAM, contexts_for, make_item, official_inputs, score_closed


def main():
    items, labels = official_inputs()
    for item in items:
        assert set(item) <= {'sample_id', 'dataset', 'task', 'query', 'options', 'videos', 'system', 'uav'}
        assert item['system'] == (UPSTREAM / 'prompts' / f"master_{item['task']}.prompt").read_text()
        for video in item['videos']:
            assert Path(video['path']).is_file(), video
        assert item['options'] == labels[item['sample_id']]['row'].get('options', [])
    for task in ('PI', 'PSS'):
        assignments = [n for n in ast.walk(ast.parse((UPSTREAM / 'run_tasks' / f'run_{task}_agent.py').read_text()))
                       if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'query' for t in n.targets)]
        assert len(assignments) == 1
        assert next(x['query'] for x in items if x['task'] == task) == ast.literal_eval(assignments[0].value)
    processor = SimpleNamespace(process_video=lambda *a, **k: (None, None, None, 30.0, 6000, 200.0))
    pss = make_item('PSS', {'id': 0, 'video': 'cook/test.mp4', 'segments': {'2': [[100, 120]], '1': [[4, 7], [9, 12]]}})
    contexts = contexts_for(pss, processor)
    assert [(c['clip_begin'], c['clip_end'], c['duration_seconds']) for c in contexts] == [(4, 12, 8), (100, 120, 20)]
    pi = make_item('PI', {'id': 0, 'video': 'movie/test.mp4', 'beginning': [0, 20], 'ending': [170, 200], 'options': ['A']})
    contexts = contexts_for(pi, processor)
    assert [(c['clip_begin'], c['clip_end']) for c in contexts] == [(0, 20), (170, 200)]
    for task in ('MOC', 'MSR'):
        item = next(x for x in items if x['task'] == task)
        contexts = contexts_for(item, processor)
        assert len(contexts) == 2 and all(c['total_frames'] > 0 for c in contexts)
        assert any(c['bbox_data'] for c in contexts), item['sample_id']
        assert all(Path(c['path'], c['image_files'][0]).is_file() for c in contexts)
    for task, answer, truth in [('BU', ['A', 'C'], ['A', 'C']), ('MOC', ['B'], 'B'),
                                ('PSS', '"2->1->3"', '2->1->3'), ('FSA', '[20,10]', [10,20]), ('CC', 'D', 'D')]:
        label = {'task': task, 'row': {'answer': truth, 'options': ['A. a', 'B. b', 'C. c', 'D. d']}}
        assert score_closed(label, answer)['score'] == 1, task
    assert score_closed({'task': 'FSA', 'row': {'answer': [10,20]}}, 'not located')['score'] == 0
    assert score_closed({'task': 'CC', 'row': {'answer': 'A', 'options': ['A. a','B. b']}}, 'B')['score'] == 0
    print(json.dumps({'items': len(items), 'task_counts': COUNTS, 'native_prompts': 'passed',
        'label_isolation': 'passed', 'clip_boundaries': 'passed', 'native_uav_metadata': 'passed', 'native_scoring': 'passed'}), flush=True)


if __name__ == '__main__':
    main()
