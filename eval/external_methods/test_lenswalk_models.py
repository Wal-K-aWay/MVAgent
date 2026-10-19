"""Check frozen algorithm preservation and flat-result resume/scoring on Modal CPU."""
import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

from lenswalk_models import TEMPLATE, patch_driver, patch_server
from common import write


def functions(source):
    return {n.name: ast.dump(n, include_attributes=False) for n in ast.parse(source).body
            if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def main():
    original = (TEMPLATE/'frozen_repo/eval/external_methods/lenswalk_full.py').read_text()
    patched = patch_driver(original)
    before, after = functions(original), functions(patched)
    assert {k for k in before if before[k] != after[k]} == {'start_actor', 'main', 'score_all'}
    assert "Semaphore(8)" in patched and 'time.monotonic()-started>1800' in patched
    assert "'expected_service.json'" in patched and "card['weights_manifest']==expected['weights_manifest']" in patched
    server = (TEMPLATE/'frozen_repo/eval/external_methods/lenswalk_server.py').read_text()
    assert functions(server) == functions(patch_server(server))
    assert patch_server(server).replace('args.model.name.lower()', "'qwen3.5-35b-a3b'") == server
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); (root/'records').mkdir()
        values = [{'sample_id': 'cvbench:72', 'answer': 'B', 'infrastructure_error': False},
                  {'sample_id': 'mvu_eval:SU:568', 'answer': '', 'infrastructure_error': True}]
        for row in values:
            (root/'records'/(row['sample_id'].replace(':', '_')+'.json')).write_text(json.dumps(row))
        tree = ast.parse(patched)
        main_node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        load = next(n for n in main_node.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                    and ast.unparse(n.value.func) == 'rows.update')
        env = dict(output=root, rows={}, read=lambda p: json.loads(p.read_text()))
        exec(compile(ast.Module(body=[load], type_ignores=[]), '<actual resume>', 'exec'), env)
        rows = env['rows']
        ids = [r['sample_id'] for r in values]+['crossvid:FSA:394']
        assert [sid for sid in ids if sid.replace(':', '_') not in rows] == ['crossvid:FSA:394']
        score = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'score_all')
        judge_one = next(n for n in ast.walk(score) if isinstance(n, ast.FunctionDef) and n.name == 'one')
        row = rows['cvbench_72']
        env.update(records={'cvbench:72': SimpleNamespace(sample=SimpleNamespace(ground_truth=['point']),
                   judge_question='', reference_answer='')}, judge=None, SCORE_PROMPT='{OUTPUT}',
                   _score_one=lambda *a, **kw: {'status': 'ok', 'score': 2}, write=write)
        exec(compile(ast.Module(body=[judge_one], type_ignores=[]), '<actual judge persistence>', 'exec'), env)
        assert env['one'](row) == 'cvbench:72'
        assert json.loads((root/'records/cvbench_72.json').read_text())['score'] == 1
        assert json.loads((root/'judgements/cvbench_72.json').read_text())['status'] == 'ok'
    print('Frozen LensWalk algorithms/parameters preserved; flat records resume including failures; model labels verified')


if __name__ == '__main__':
    main()
