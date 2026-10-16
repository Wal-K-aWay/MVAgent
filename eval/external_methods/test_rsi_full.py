"""Remote CPU checks using real RSI requests plus missing/malformed-answer cases."""
from pathlib import Path
import json
import tempfile
import tarfile
from common import write
from lenswalk_full import method_config,archive_attempt
from rsi_outcome import inspect


def main():
    spec=method_config('rsi')
    assert spec['server']=='native_server' and spec['upstream']=='Video-RSI' and spec['question_timeout']==7200
    base=Path('/runs/devbox/external_original_images_20261015/rsi/cvbench_764')
    card=json.loads((base/'service_card.json').read_text())
    row=inspect(base,card)
    assert row['answer']=='B' and row['terminal']=='finish' and not row['infrastructure_error']
    assert row['calls']>0 and row['visual_calls']>0 and row['output_tokens']>0
    wrong=dict(card,worker=dict(card['worker'],pid=-1))
    try:inspect(base,wrong)
    except AssertionError:pass
    else:raise AssertionError('Accepted a mismatched model worker')
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        assert inspect(root,card)['infrastructure_error']
        write(root/'result.json',dict(status='invalid_decision',answer=None))
        row=inspect(root,card)
        assert row['terminal']=='invalid_decision' and row['answer']=='' and not row['infrastructure_error']
        write(root/'result.json',dict(status='engineering_error',error='candidate timeout',answer=None))
        assert inspect(root,card)['infrastructure_error']
        attempt=root/'attempt-raw';attempt.mkdir();(attempt/'output.txt').write_text('原始轨迹')
        archive=archive_attempt(attempt,compress=False)
        assert archive['path'].endswith('.tar') and not attempt.exists()
        with tarfile.open(archive['path'],'r:') as stream:
            assert stream.extractfile('attempt-raw/output.txt').read()=='原始轨迹'.encode()
    print('RSI real-response audit, failure separation, worker binding and uncompressed archive passed')


if __name__=='__main__':main()
