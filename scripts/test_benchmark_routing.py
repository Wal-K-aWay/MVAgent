"""Small CPU self-check for benchmark request scheduling; run in the remote image."""
from collections import Counter
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import benchmark_qwen35_throughput as bench


def main():
    active, peaks = Counter(), Counter()
    lock = threading.Lock()

    def request(client, body, *, endpoint):
        assert client.headers['X-data-parallel-rank'] == endpoint[-1]
        with lock:
            active[endpoint] += 1
            peaks[endpoint] = max(peaks[endpoint], active[endpoint])
        try:
            time.sleep(.005)
            if body == b'error':
                raise RuntimeError('expected self-check failure')
            return dict(token_ids=[1], token_ids_sha256='output',
                        prompt_token_ids_sha256='prompt', seconds=.005, output_tokens=1)
        finally:
            with lock:
                active[endpoint] -= 1

    with (tempfile.TemporaryDirectory() as tmp,
          patch.object(bench, 'request_once', request), patch.object(bench, 'event')):
        root = Path(tmp)
        for dynamic in [False, True]:
            references = {}
            directory = root / str(dynamic)
            directory.mkdir()
            measured = bench.run_pass(
                SimpleNamespace(output=root), directory, 'check', ['http://rank0', 'http://rank1'],
                {'ok': b'ok', 'error': b'error'}, 1, ['error'] + ['ok'] * 15, references,
                phase='measure', dynamic_routing=dynamic,
                client_headers=[{'X-data-parallel-rank': str(i)} for i in range(2)])
            assert measured['samples'] == 15 and len(measured['errors']) == 1
            assert not measured['stable'] and not measured['mismatches']
            assert references['ok']['token_ids'] == [1]
            assert peaks == {'http://rank0': 1, 'http://rank1': 1}
            assert not any(active.values())
    print('routing self-check passed: pinned/dynamic capacity, headers, errors, references')


if __name__ == '__main__':
    main()
