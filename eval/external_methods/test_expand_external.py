"""Check expansion ownership and compatibility with the actual frozen source."""
import ast
from pathlib import Path
from expand_external import assign, read


def main():
    ids = [f'cvbench:{i}' for i in range(24)]
    saved = {sid: {'infrastructure_error': i == 0} for i, sid in enumerate(ids[:8])}
    costs = {sid: 1000 if i < 8 else 1+i for i, sid in enumerate(ids)}
    groups, loads = assign(ids, saved, costs)
    assert len(groups) == 4 and len(set(sum(groups, []))) == sum(map(len, groups)) == 24
    assert sum(loads) == sum(costs[sid] for sid in ids if sid not in saved)
    assert max(loads)-min(loads) <= max(costs[sid] for sid in ids if sid not in saved)
    assert all(sum(sid in saved for sid in group) == 2 for group in groups)
    assert assign(ids, saved, costs) == (groups, loads) and saved[ids[0]]['infrastructure_error']
    tree = ast.parse(Path(__file__).with_name('drain_external.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    timeout = next(n for n in function.body if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == 'question_timeout')
    for method, old in [('lenswalk', 'lenswalk_27b_parallel_20261020'), ('rsi', 'rsi_27b_16gpu_20261020')]:
        root = Path('/runs/devbox')/(old+'-shard0')
        manifest = read(root/'manifest.json')
        env = {'method': method}
        exec(compile(ast.Module(body=[timeout], type_ignores=[]), '<drain budget>', 'exec'), env)
        assert env['question_timeout'] == manifest['question_timeout_seconds']
        source = (root/'frozen_repo/eval/external_methods/lenswalk_full.py').read_text()
        assert "EXPECTED=manifest['expected_counts']" in source
        assert (root/('client_environment.json' if method=='rsi' else 'client_environment.tar.gz')).exists()
    print('Disjoint balanced pending owners, saved failures retained, actual frozen budgets and runtime paths verified')


if __name__ == '__main__':
    main()
