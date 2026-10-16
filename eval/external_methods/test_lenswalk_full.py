"""Remote CPU regressions for full-panel caching and terminal-state audit."""
import json
from pathlib import Path
import tempfile
import tarfile
import threading
from types import SimpleNamespace

from common import write
from lenswalk_full import media_key,prepare_item,archive_attempt
from lenswalk_outcome import inspect


def main():
    videos={'Video 1':'/one.mp4','Video 2':'/two.mp4'}
    assert media_key(videos)!=media_key(dict(reversed(list(videos.items()))))
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);video=root/'video.mp4';video.write_bytes(b'cached-test-media')
        meta=root/'timeline.json'
        write(meta,dict(duration=4,segments=[dict(video_id=k,source=v,start=i*2,end=i*2+2,original_duration=2)
                                             for i,(k,v) in enumerate(videos.items())]))
        write(root/'media_cache'/f'{media_key(videos)}.json',dict(video_path=str(video),timeline_path=str(meta)))
        for sid,question in [('first','First question'),('second','A different question')]:
            record=SimpleNamespace(sample_id=sid,sample=SimpleNamespace(videos=videos,question=question,options=[]))
            item=json.loads(prepare_item(root,record,threading.Lock()).read_text())
            assert item['sample_id']==sid and item['question'].endswith(question)
            assert item['video_path']==str(video) and '2.00 seconds' in item['question']
        attempt=root/'attempt-test';attempt.mkdir()
        (attempt/'raw.txt').write_text('完整原始记录\n')
        archive=archive_attempt(attempt)
        assert not attempt.exists() and set(archive['files'])=={'raw.txt'}
        with tarfile.open(archive['path']) as stream:
            assert stream.extractfile('attempt-test/raw.txt').read()=='完整原始记录\n'.encode()
    smoke=Path('/runs/devbox/external_lenswalk_20261016_r3')
    card=json.loads((smoke/'startup_verification.json').read_text())
    expected={'cvbench_764':'natural_text','mvu_eval_TR_1585':'finish','crossvid_MSR_361':'unfinished_tool_plan',
              'crossvid_PSS_341':'finish','crossvid_FSA_394':'finish','crossvid_CCQA_73':'finish'}
    rows=[inspect(smoke/'lenswalk'/sid,card) for sid in expected]
    assert [r['terminal'] for r in rows]==list(expected.values())
    assert sum(r['calls'] for r in rows)==138 and sum(r['output_tokens'] for r in rows)==20506
    assert not any(r['infrastructure_error'] for r in rows)
    wrong=dict(card,worker=dict(card['worker'],pid=-1))
    try:inspect(smoke/'lenswalk/cvbench_764',wrong)
    except AssertionError:pass
    else:raise AssertionError('Accepted a response from a different worker')
    print('Ordered media caching, per-question prompt isolation, six real terminal outcomes and worker audit passed')


if __name__=='__main__':main()
