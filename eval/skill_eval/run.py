#!/usr/bin/env python3
"""Freeze and run the role-wise skill evolution development experiment."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(PROJECT_ROOT / 'src'), str(PROJECT_ROOT)]
import yaml
from mvagent.utils.io import file_fingerprint, hash_json, tree_hash, write_json
from mvagent.utils.snapshot import ensure_source_snapshot


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    for flag in ('config', 'optimizer-config', 'runtime-config', 'execution-config', 'split-manifest', 'dataset-root'):
        parser.add_argument('--' + flag, type=Path)
    parser.add_argument('--judge-endpoints', help='Comma-separated fixed local Judge endpoints')
    return parser


def _prepare(args):
    output = args.output.expanduser().absolute()
    manifest_path = output / 'manifest.json'
    frozen = output / 'frozen'
    if args.resume:
        if any(getattr(args, name) is not None for name in ('config','optimizer_config','runtime_config',
                'execution_config','split_manifest','dataset_root','judge_endpoints')):
            raise ValueError('Resume accepts only --output and --resume; frozen configuration is authoritative')
        manifest = json.loads(manifest_path.read_text())
    else:
        if not args.execution_config or not args.split_manifest or not args.judge_endpoints:
            raise ValueError('New runs require execution-config, split-manifest and judge-endpoints')
        output.mkdir(parents=True, exist_ok=False)
        inputs = {'search': args.config or PROJECT_ROOT/'configs/skill_evolution/evolution.yaml',
                  'optimizer': args.optimizer_config or PROJECT_ROOT/'configs/skill_evolution/llm_generation.yaml',
                  'runtime': args.runtime_config or PROJECT_ROOT/'configs/inference/modal_qwen35_35b_a3b_no_skill.yaml',
                  'execution': args.execution_config, 'split': args.split_manifest}
        config_hashes = {}
        for name,path in inputs.items():
            payload = yaml.safe_load(Path(path).read_text())
            if name == 'optimizer':
                from skill_evolution.configs.models import validate_model_settings
                validate_model_settings(payload)
            if name == 'runtime':
                from mvagent.utils.tools import looks_like_env_var_name
                for model in payload.get('models', {}).values():
                    key = model.get('api_key')
                    if key and key != 'unused' and not looks_like_env_var_name(key):
                        raise ValueError('Runtime api_key must name an environment variable')
            destination = output / 'configs' / f'{name}.json'
            write_json(destination, payload)
            config_hashes[name] = file_fingerprint(destination)
        ensure_source_snapshot(frozen)
        # Freeze the public evaluator, including this coordinator; do not copy local historical implementations.
        target = frozen / 'eval'; target.mkdir(parents=True)
        for name in ('__init__.py', 'data.py', 'benchmarks', 'agent_eval', 'skill_eval'):
            source = PROJECT_ROOT / 'eval' / name
            if source.is_dir():
                shutil.copytree(source, target/name, ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            else:
                shutil.copy2(source, target/name)
        commit = os.environ.get('MVAGENT_SOURCE_COMMIT')
        if not commit and shutil.which('git'):
            result = subprocess.run(['git','-C',str(PROJECT_ROOT),'rev-parse','HEAD'],capture_output=True,text=True)
            commit = result.stdout.strip() if result.returncode == 0 else None
        manifest = {'source_commit':commit, 'source_sha256':tree_hash(frozen/'src'),
                    'evaluation_sha256':tree_hash(frozen/'eval'), 'config_sha256':config_hashes,
                    'dataset_root':str((args.dataset_root or Path('/assets')).absolute()),
                    'judge_endpoints':[part.strip() for part in args.judge_endpoints.split(',') if part.strip()]}
        write_json(manifest_path, manifest)
    if tree_hash(frozen/'src') != manifest['source_sha256'] or tree_hash(frozen/'eval') != manifest['evaluation_sha256']:
        raise ValueError('Frozen source changed')
    for name,digest in manifest['config_sha256'].items():
        if file_fingerprint(output/'configs'/f'{name}.json') != digest:
            raise ValueError(f'Frozen {name} configuration changed')
    return output, manifest


def main():
    args = _parser().parse_args()
    output, manifest = _prepare(args)
    entry = output / 'frozen/eval/skill_eval/run.py'
    if Path(__file__).resolve() != entry.resolve():
        env = {**os.environ, 'MVAGENT_PROJECT_ROOT':str(output/'frozen'),
               'PYTHONPATH':str(output/'frozen/src') + os.pathsep + str(output/'frozen')}
        if manifest['source_commit']:
            env['MVAGENT_SOURCE_COMMIT'] = manifest['source_commit']
        os.execve(sys.executable, [sys.executable,str(entry),'--output',str(output),'--resume'],env)
    from skill_evolution.configs.evolution import EvolutionConfig
    from skill_evolution.configs.models import load_client
    from skill_evolution.algorithms.rolewise.optimizer import evolve
    from eval.skill_eval.evaluator import LibraryEvaluator
    config_dir = output/'configs'
    config = EvolutionConfig.from_dict(json.loads((config_dir/'search.json').read_text()))
    runtime = json.loads((config_dir/'runtime.json').read_text())
    client = load_client(config_dir/'optimizer.json')
    evaluator = LibraryEvaluator(output=output, runtime=runtime, execution=config_dir/'execution.json',
        split_path=config_dir/'split.json', dataset_root=manifest['dataset_root'],
        endpoints=manifest['judge_endpoints'], identity=hash_json(manifest))
    try:
        summary = evolve(client=client,runtime=runtime,config=config,evaluator=evaluator,output=output)
        print(json.dumps(summary), flush=True)
    except BaseException as exc:
        write_json(output/'failure.json', {'error':str(exc)}, redact=client.api_key)
        raise


if __name__ == '__main__':
    main()
