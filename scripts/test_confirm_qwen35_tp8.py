"""Remote CPU self-check of restart coverage and failure accounting; no inference."""
from contextlib import nullcontext
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import confirm_qwen35_tp8 as probe


def main():
    for fail in [False, True]:
        calls = []

        def run_pass(args, directory, label, endpoints, bodies, concurrency, tasks, references, **kwargs):
            assert endpoints == [probe.ENDPOINT] and concurrency == 1
            calls.append((directory.parent.name, directory.name, label, len(tasks)))
            for name in tasks:
                references.setdefault(name, {'token_ids': [7], 'prompt_token_ids_sha256': 'self-check'})
            mismatch = fail and label == 'after_restart'
            return {'name': label, 'samples': len(tasks), 'stable': not mismatch,
                    'mismatches': [{'case': tasks[0]}] if mismatch else [], 'errors': []}

        def evaluate(*args):
            assert args[0].workers == 1 and not args[0].media_uuids
            return {'name': args[2], 'samples': 30, 'stable': True, 'mismatches': [], 'errors': []}

        with (tempfile.TemporaryDirectory() as tmp,
              patch.object(probe, 'serve', lambda *_: nullcontext()),
              patch.object(probe, 'run_pass', run_pass),
              patch.object(probe, 'evaluate_pass', evaluate), patch.object(probe, 'event')):
            result = probe.run_model(SimpleNamespace(output=Path(tmp)), '9B',
                                     {f'long{i}': b'input' for i in range(8)}, [], {}, {}, None)
            assert result['error'] is None, result['error']
            assert result['samples'] == 178 and len(result['passes']) == 10
            assert result['stable'] is (not fail)
            assert result['mismatches'] == (2 if fail else 0)
            assert {restart for restart, *_ in calls} == {'restart0', 'restart1'}
            assert len(result['archived_output_comparison']) == 4
    print('TP8 self-check passed: archived request bytes, serial capacity, restart coverage, mismatch rejection')


if __name__ == '__main__':
    main()
