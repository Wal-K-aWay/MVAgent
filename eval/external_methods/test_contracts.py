"""Small adapter contracts; run in the remote experiment environment."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import json

from prepare import timeline, verify_concat_clock
from native_server import configure


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
        for answer in ('AB', '2->4->1->3', '12.5,19', 'A natural-language answer'):
            assert module.parse_decision(json.dumps({'type':'answer','answer':answer}), {})['answer'] == answer
        for bad in ('', None, 3):
            try:
                module.parse_decision(json.dumps({'type':'answer','answer':bad}), {'A':'one','B':'two'})
            except ValueError:
                pass
            else:
                raise AssertionError(f'Accepted invalid answer {bad!r}')
        name = 'solver_full_workspace/engine/services.py'
        assert (target/name).read_text() == (source/name).read_text()
    text = timeline([dict(video_id='video_2', start=10.25, end=30.75, original_duration=20.5)])
    assert text.startswith('This is a multi-video understanding task.')
    assert '10.25 seconds' in text and '30.75 seconds' in text and 'subtract its start offset' in text
    assert verify_concat_clock([(0, .0407)], [0], .04) == .0407
    for clock in ([(.001, .04)], [(0, .042)], [(0, .04), (.04, .04)]):
        try:
            verify_concat_clock(clock, [0], .04)
        except ValueError:
            pass
        else:
            raise AssertionError('Accepted changed timestamps, packet count, or excessive duration drift')
    server = configure()
    assert server.ENGINE_CONFIG['limit_mm_per_prompt'] == {'image':512, 'video':8}
    for temperature, maximum in ((0,8192), (.1,700), (.1,500), (0,220), (.2,500)):
        body = dict(model='local', messages=[dict(role='user', content='test')],
                    temperature=temperature, max_tokens=maximum, thinking={'type':'disabled'})
        before = json.dumps(body)
        actual = server.validate_request(body, 'local')
        assert actual['temperature'] == temperature and actual['max_tokens'] == maximum
        assert json.dumps(body) == before
    try:
        server.validate_request(dict(body, temperature=float('nan')), 'local')
    except ValueError:
        pass
    else:
        raise AssertionError('Accepted an invalid temperature')
    print('Adapter contracts passed')


if __name__ == '__main__':
    main()
