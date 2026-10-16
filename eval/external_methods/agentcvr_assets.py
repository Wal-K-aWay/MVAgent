"""Run on modal-gpu: download author checkpoints and merge on Modal CPU."""
import os
from pathlib import Path
import sys

import modal

PROJECT = Path.home() / 'wxu-evolve-agent'
SOURCE = PROJECT / 'external_sources/AgentCVR-568b402'
image = merge_image = None
if modal.is_local():
    sys.path.insert(0, str(PROJECT / 'modal'))
    from env_image import image as base_image
    image = (base_image.uv_pip_install('openai-whisper==20250625', 'tensordict==0.10.0',
                                     'hydra-core==1.3.2', 'accelerate==1.12.0', 'ray==2.48.0')
             .add_local_dir(str(SOURCE), '/opt/AgentCVR', ignore=['.git']))
    merge_image = (modal.Image.debian_slim(python_version='3.12')
        .uv_pip_install('torch==2.8.0', index_url='https://download.pytorch.org/whl/cpu')
        .uv_pip_install('transformers==4.56.1', 'tensordict==0.10.0', 'hydra-core==1.3.2',
                        'accelerate==1.12.0', 'ray==2.48.0', 'numpy==2.2.6', 'pillow')
        .add_local_dir(str(SOURCE), '/opt/AgentCVR', ignore=['.git']))
weights = modal.Volume.from_name('wxu-sgl-evolve-agent-weight-20261006')
runs = modal.Volume.from_name('wxu-evolve-agent-runs-20261006')
app = modal.App('wxu-evolve-agent-agentcvr-assets-20261016')


@app.function(image=merge_image, cpu=8, memory=131072, timeout=3600,
              volumes={'/weights': weights, '/runs': runs})
def merge_checkpoint():
    import subprocess
    env = dict(os.environ, PYTHONPATH='/opt/AgentCVR/verl', OMP_NUM_THREADS='8')
    with Path('/runs/devbox/agentcvr_20261016/merge_torch28.log').open('w') as log:
        subprocess.run([sys.executable, '-m', 'verl.model_merger', 'merge', '--backend', 'fsdp',
                        '--local_dir', '/weights/AgentCVR-8B-original/actor',
                        '--target_dir', '/weights/AgentCVR-8B-merged'],
                       env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    weights.commit()
    runs.commit()


@app.function(image=image, cpu=8, memory=131072, timeout=14400,
              volumes={'/weights': weights, '/runs': runs})
def prepare():
    import hashlib
    import json
    import subprocess
    import time
    from huggingface_hub import HfApi, snapshot_download

    root = Path('/runs/devbox/agentcvr_20261016')
    root.mkdir(parents=True, exist_ok=True)
    manifest = (json.loads((root / 'assets.json').read_text()) if (root / 'assets.json').exists()
                else {'stage': 'starting', 'models': {}, 'started': time.time()})
    if 'error' in manifest:
        manifest.setdefault('previous_errors', []).append(manifest.pop('error'))

    def save(stage):
        manifest.update(stage=stage, updated=time.time())
        (root / 'assets.json').write_text(json.dumps(manifest, indent=2))
        weights.commit()
        runs.commit()
        print(json.dumps({'stage': stage, 'updated': manifest['updated']}), flush=True)

    def sha(path):
        h = hashlib.sha256()
        with path.open('rb') as f:
            for chunk in iter(lambda: f.read(8 * 1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    try:
        for repo, revision, directory, patterns in [
            ('xiaohua616/qwen8b_crossvidRL', '0ca8538758507589a5bada39d2377847649adc09',
             'AgentCVR-8B-original', ['README.md', 'actor/model_world_size_*.pt',
                                     'actor/fsdp_config.json', 'actor/huggingface/*']),
            ('Qwen/Qwen3-VL-8B-Thinking', '92f3c4b4feadd3a016ef468d103bb5f58b2a2c6b',
             'Qwen3-VL-8B-Thinking', None),
        ]:
            if repo in manifest['models']:
                assert manifest['models'][repo]['revision'] == revision
                print('reuse verified download', repo, flush=True)
                continue
            save('downloading ' + repo)
            target = Path('/weights') / directory
            snapshot_download(repo, revision=revision, local_dir=target,
                              allow_patterns=patterns, max_workers=4)
            info = HfApi().model_info(repo, revision=revision, files_metadata=True)
            checked = []
            for item in info.siblings:
                path = target / item.rfilename
                if not path.is_file():
                    continue
                assert path.stat().st_size == item.size, item.rfilename
                digest = sha(path)
                if item.lfs:
                    assert digest == item.lfs.sha256, item.rfilename
                checked.append({'file': item.rfilename, 'bytes': item.size, 'sha256': digest})
            assert checked
            manifest['models'][repo] = {'revision': revision, 'path': str(target), 'files': checked}
            save('verified ' + repo)
        save('merging Master FSDP')
        merged = Path('/weights/AgentCVR-8B-merged')
        merge_checkpoint.remote()
        weights.reload()
        from transformers import AutoConfig
        config = AutoConfig.from_pretrained(merged)
        assert config.model_type == 'qwen3', config.model_type
        tensors = list(merged.glob('*.safetensors'))
        assert tensors, 'Merger produced no safetensors'
        manifest['merged'] = {'path': str(merged), 'model_type': config.model_type,
                              'files': [{'file': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)}
                                        for p in tensors]}
        save('downloading Whisper')
        import whisper
        audio_dir = Path('/weights/Whisper-large-v3')
        audio_dir.mkdir(exist_ok=True)
        audio_path = Path(whisper._download(whisper._MODELS['large-v3'], str(audio_dir), False))
        manifest['whisper'] = {'path': str(audio_path), 'sha256': sha(audio_path),
                               'bytes': audio_path.stat().st_size}
        manifest['dependencies'] = subprocess.check_output(
            [sys.executable, '-m', 'pip', 'freeze'], text=True).splitlines()
        save('completed')
    except Exception as exc:
        manifest['error'] = f'{type(exc).__name__}: {exc}'
        save('failed')
        raise


@app.local_entrypoint()
def main():
    prepare.remote()
