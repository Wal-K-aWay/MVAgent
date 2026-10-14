"""Small adapter contracts; run in the remote experiment environment."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile

from prepare import timeline


def main():
    root = Path(__file__).resolve().parents[2]
    source = root/'external_sources/Video-RSI'
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        subprocess.run(['cp', '-a', str(source)+ '/.', str(target)], check=True)
        with (Path(__file__).parent/'video_rsi.patch').open() as patch:
            subprocess.run(['patch', '-p1'], cwd=target, stdin=patch, check=True)
        spec = importlib.util.spec_from_file_location('rsi_answers', target/'artifacts/final_harness/answers.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for answer in ('AB', '2->4->1->3', '12.5,19', 'The second video uses a lid.'):
            import json
            assert module.parse_decision(json.dumps({'type':'answer','answer':answer}), {})['answer'] == answer
        for bad in ('', None, 3):
            try:
                module.parse_decision(json.dumps({'type':'answer','answer':bad}), {})
            except ValueError:
                pass
            else:
                raise AssertionError(f'Accepted invalid answer {bad!r}')
    text = timeline([dict(video_id='video_2', start=10.25, end=30.75, original_duration=20.5)])
    assert '10.250000 seconds' in text and '30.750000 seconds' in text and 'subtract its start offset' in text
    print('Adapter contracts passed')


if __name__ == '__main__':
    main()
