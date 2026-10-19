"""Freeze the completed LensWalk protocol for fresh 9B and 27B full-panel runs."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil

from common import sha256, write

TEMPLATE = Path('/runs/devbox/lenswalk_full_35b_parallel_media_20261018')
WEIGHTS = Path('/runs/devbox/lenswalk_models_setup_20261019/weights.json')
EXPECTED = {'cvbench': 997, 'mvu_eval': 1824, 'crossvid': 2500}


def replace_once(source, before, after):
    assert source.count(before) == 1, before
    return source.replace(before, after)


def patch_driver(source):
    changes = [
        ("'--model','/weights/Qwen3.5-35B-A3B'", "'--model',read(episode.parents[1]/'manifest.json')['model_root']"),
        ("models={'35B-A3B':{'finished':len(values)}}", "models={manifest['model']:{'finished':len(values)}}"),
        ("rows.update({p.parent.name:read(p) for p in (output/'lenswalk').glob('*/record.json')})",
         "rows.update({p.stem:read(p) for p in (output/'records').glob('*.json')})"),
        ("                outcome['raw_archive']=archive_attempt(attempt)\n",
         "                outcome['raw_archive']=archive_attempt(attempt)\n"
         "                archive=Path(outcome['raw_archive']['path'])\n"
         "                target=output/'raw'/(directory.name+'-'+archive.name)\n"
         "                archive.replace(target);outcome['raw_archive']['path']=str(target)\n"),
        ("                write(directory/'record.json',outcome)\n",
         "                write(output/'records'/(directory.name+'.json'),outcome)\n"
         "                if not any(directory.iterdir()):directory.rmdir()\n"),
        ("                directory=output/'lenswalk'/row['sample_id'].replace(':','_');write(directory/'judge.json',result)",
         "                directory=output/'records';key=row['sample_id'].replace(':','_');write(output/'judgements'/(key+'.json'),result)"),
        ("write(directory/'record.json',row)", "write(directory/(key+'.json'),row)"),
    ]
    for before, after in changes:
        source = replace_once(source, before, after)
    compile(source, '<model-aware LensWalk driver>', 'exec')
    return source


def patch_server(source):
    return replace_once(source, "args.log_dir,'qwen3.5-35b-a3b')", "args.log_dir,args.model.name.lower())")


def initialize(output, model):
    from datetime import datetime, timezone
    assert model in ('9B', '27B')
    assert not output.exists(), 'Never overwrite an evaluation'
    original = json.loads((TEMPLATE/'manifest.json').read_text())
    assert json.loads((TEMPLATE/'progress.json').read_text())['phase'] == 'completed_with_errors'
    ids = json.loads((TEMPLATE/'samples.json').read_text())
    assert len(ids) == len(set(ids)) == sum(EXPECTED.values())
    assert sha256(TEMPLATE/'samples.json') == original['samples_sha256']
    weights = json.loads(WEIGHTS.read_text())[model]
    assert weights['shards'] and weights['files']['config.json']
    frozen = output/'frozen_repo'
    shutil.copytree(TEMPLATE/'frozen_repo', frozen, ignore=shutil.ignore_patterns('__pycache__'))
    driver = frozen/'eval/external_methods/lenswalk_full.py'
    server = frozen/'eval/external_methods/lenswalk_server.py'
    assert sha256(driver) == original['driver_sha256']
    driver.write_text(patch_driver(driver.read_text()))
    server.write_text(patch_server(server.read_text()))
    source = Path(__file__).resolve().parent
    commit = (source.parents[1]/'.git/HEAD').read_text().strip()
    (frozen/'.git/HEAD').write_text(commit+'\n')
    for name in ('lenswalk_models.py', 'test_lenswalk_models.py'):
        shutil.copy2(source/name, frozen/'eval/external_methods'/name)
    files = [p for p in frozen.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with ThreadPoolExecutor(max_workers=8) as pool:
        hashes = dict(zip((str(p.relative_to(frozen)) for p in files), pool.map(sha256, files)))
    allowed = {'eval/external_methods/lenswalk_full.py', 'eval/external_methods/lenswalk_server.py', '.git/HEAD'}
    assert all(hashes.get(name) == value for name, value in original['source_hashes'].items() if name not in allowed)
    for name in ('samples.json', 'prepared/private_labels.json'):
        (output/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATE/name, output/name)
    (output/'client_environment.tar.gz').symlink_to((TEMPLATE/'client_environment.tar.gz').resolve())
    expected = json.loads((TEMPLATE/'expected_service.json').read_text())
    expected['weights_manifest'] = weights
    expected['execution']['lenswalk_transport_sha256'] = sha256(server)
    write(output/'expected_service.json', expected)
    for name in ('lenswalk', 'records', 'raw', 'judgements', 'episodes'):
        (output/name).mkdir()
    # Put one existing question from each benchmark first; keep the panel and its hashes unchanged.
    first = [next(sid for sid in ids if sid.startswith(dataset+':')) for dataset in EXPECTED]
    order = first + [sid for sid in ids if sid not in first]
    now = datetime.now(timezone.utc).isoformat()
    manifest = dict(original, created_at=now, model=model, model_root='/weights/Qwen3.5-'+model,
                    template=str(TEMPLATE), source_snapshot=str(frozen), recovery_order=order,
                    driver_commit=commit, driver_sha256=sha256(driver), source_hashes=hashes,
                    inherited_count=0, result_layout='Flat records/raw/judgements; only active questions have scratch directories')
    for key in ('recovery_from', 'recovery_commit', 'existing_cached_groups'):
        manifest.pop(key, None)
    write(output/'manifest.json', manifest)
    write(output/'inherited_records.json', {})
    write(output/'progress.json', dict(phase='prepared', model=model, expected=len(ids), completed=0,
                                     updated_at=now, models={model: {'finished': 0}}))
    write(output/'source_audit.json', dict(template_manifest_sha256=sha256(TEMPLATE/'manifest.json'),
          unchanged_original_files=len(original['source_hashes'])-len(allowed), permitted_changes=sorted(allowed),
          sample_ids_identical=True, inherited_answers=0, expected_weights_sha256=sha256(WEIGHTS)))
    print(json.dumps(dict(model=model, expected=len(ids), first=first, source_commit=commit,
                         original_runtime_preserved=True, output=str(output))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--model', choices=['9B', '27B'], required=True)
    args = parser.parse_args()
    initialize(args.output, args.model)
