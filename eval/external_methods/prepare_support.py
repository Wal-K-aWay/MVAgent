"""Download the original VAM visual embedder on Modal, with a pinned revision."""
import json
from pathlib import Path
from huggingface_hub import snapshot_download
from common import write


root = Path('/runs/devbox/external_methods_20261014/support')
repo = 'Qwen/Qwen3-VL-Embedding-8B'
revision = '2c4565515e0f265c6511776e7193b22c0968ddc7'
path = root / 'Qwen3-VL-Embedding-8B'
write(root/'embedding_download.json', dict(repository=repo, revision=revision, status='downloading'))
snapshot_download(repo, revision=revision, local_dir=path, max_workers=4,
                  allow_patterns=['*.json', '*.safetensors', '*.txt', '*.jinja', '*.model'])
write(root/'embedding_download.json', dict(repository=repo, revision=revision, status='complete', path=str(path)))
print(json.dumps(dict(repository=repo, revision=revision, path=str(path))))
