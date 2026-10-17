"""Freeze the exact project adapters and upstream sources before any model calls."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from common import sha256, write


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    destination = args.output/'frozen_repo'
    if destination.exists():
        raise FileExistsError('Frozen source already exists; do not overwrite it')
    temporary = args.output/'frozen_repo.tmp'
    temporary.mkdir(parents=True)
    for name in ('src','eval','configs','external_sources'):
        shutil.copytree(root/name, temporary/name, ignore=shutil.ignore_patterns('__pycache__','.cache','.git'))
    write(temporary/'source_manifest.json', dict(
        project_commit=(root/'.devbox_head').read_text().strip() if (root/'.devbox_head').exists() else 'see source hashes',
        upstream=json.loads((root/'eval/external_methods/sources.json').read_text()),
        files={str(path.relative_to(temporary)):sha256(path) for path in sorted(temporary.rglob('*')) if path.is_file()}))
    for repository, patch_name in [('Video-RSI','video_rsi.patch'), ('LensWalk','lenswalk.patch')]:
        with (temporary/'eval/external_methods'/patch_name).open() as patch:
            subprocess.run(['patch','-p1'],cwd=temporary/'external_sources'/repository,stdin=patch,check=True)
    write(temporary/'adapted_source_sha256.json',{str(path.relative_to(temporary)):sha256(path)
        for path in sorted((temporary/'external_sources').rglob('*')) if path.is_file()})
    temporary.rename(destination)
    print(destination)


if __name__ == '__main__':
    main()
