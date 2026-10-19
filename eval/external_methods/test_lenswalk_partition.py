"""Remote CPU check: disjoint ownership, failure retention, unchanged execution."""
import ast
from pathlib import Path
import subprocess
import sys
import time
from drain_lenswalk import process
from lenswalk_partition import partition, patch_driver


def main():
    ids = [f'{dataset}:{i}' for dataset in ('cvbench', 'mvu_eval', 'crossvid') for i in range(11)]
    completed = {ids[0]: {'infrastructure_error': True}, ids[2]: {'answer': ''}, ids[15]: {'answer': 'B'}}
    groups = partition(ids, completed)
    assert not set(groups[0]) & set(groups[1])
    assert sorted(groups[0]+groups[1]) == sorted(ids)
    pending = [[sid for sid in group if sid not in completed] for group in groups]
    assert len(pending[0])+len(pending[1]) == len(ids)-len(completed)
    for dataset in ('cvbench', 'mvu_eval', 'crossvid'):
        assert abs(sum(s.startswith(dataset+':') for s in pending[0])-sum(s.startswith(dataset+':') for s in pending[1])) <= 1
    for done in ({}, dict.fromkeys(ids)):
        assert set(sum(partition(ids, done), [])) == set(ids)
    try:
        partition(ids+[ids[0]], {})
        raise RuntimeError('Duplicate accepted')
    except AssertionError:
        pass
    source = Path('/runs/devbox/lenswalk_full_9b_20261019/frozen_repo/eval/external_methods/lenswalk_full.py').read_text()
    patched = patch_driver(source)
    before = {n.name: ast.dump(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    after = {n.name: ast.dump(n) for n in ast.parse(patched).body if isinstance(n, ast.FunctionDef)}
    assert {k for k in before if before[k] != after[k]} == {'main'}
    assert patched.replace('    global EXPECTED\n', '').replace("    EXPECTED=manifest['expected_counts']\n", '') == source
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(.2); raise SystemExit(7)'])
    try:
        info = process(child.pid)
        assert abs(time.time()-info['started_epoch']) < 2
        deadline = time.monotonic()+10
        while process(child.pid)['state'] != 'Z' and time.monotonic()<deadline:
            time.sleep(.1)
        assert process(child.pid)['returncode'] == 7
    finally:
        child.wait()
    print('Disjoint full coverage; completed failures/empty answers retained; pending balanced; runtime byte-preserved except counts')


if __name__ == '__main__':
    main()
