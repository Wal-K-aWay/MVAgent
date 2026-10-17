"""Delete the retired VAM-only runtime assets; preserve results and frozen runs."""
import json
from pathlib import Path
import shutil


ROOT = Path('/runs/devbox/external_methods_20261014/support')
TARGETS = ('Qwen3-VL-Embedding-8B', 'upstream_clients_20261015/vam')
output = Path('/runs/devbox/vam_retirement_20261016')
output.mkdir(exist_ok=True)
assert not (output/'manifest.json').exists(), 'Retirement already recorded; do not overwrite it'
entries = []
for relative in TARGETS:
    target = ROOT/relative
    assert target.is_dir() and not target.is_symlink() and target.resolve().is_relative_to(ROOT.resolve())
    files = [p for p in target.rglob('*') if p.is_file() and not p.is_symlink()]
    entries.append(dict(path=str(target), bytes=sum(p.stat().st_size for p in files), files=len(files)))
for name in ('embedding_download.json', 'upstream_clients_20261015/vam_manifest.json'):
    shutil.copy2(ROOT/name, output/Path(name).name)
(output/'source.py').write_bytes(Path(__file__).read_bytes())
(output/'manifest.json').write_text(json.dumps(dict(status='deleting', targets=entries), indent=2))
for entry in entries:
    shutil.rmtree(entry['path'])
    assert not Path(entry['path']).exists()
(output/'manifest.json').write_text(json.dumps(dict(status='completed', targets=entries,
    deleted_bytes=sum(e['bytes'] for e in entries),
    retained='Historical answers, scores, frozen runs, all Qwen3.5 Actors, and shared Qwen3-Embedding-8B.'), indent=2))
print((output/'manifest.json').read_text())
