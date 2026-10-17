"""Stream the prepared result archive through modal-gpu and verify it on Lightsail."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time

EXPORT = 'devbox/agentcvr_lightsail_export_20261017'
SDK = '~/.local/share/uv/tools/modal/bin/python'
PREFIX = "import modal,sys\nv=modal.Volume.from_name('wxu-evolve-agent-runs-20261006',environment_name='zheng-dev')\n"


def ssh_python(code):
    return ['ssh', '-T', 'modal-gpu', SDK + ' -c ' + shlex.quote(PREFIX + code)]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    destination = parser.parse_args().destination.resolve()
    assert not destination.exists(), f'Destination already exists: {destination}'
    stage = destination.with_name(destination.name + '.partial')
    assert not stage.exists(), f'Preserving previous partial transfer: {stage}'
    bundle = json.loads(subprocess.check_output(ssh_python(
        f"sys.stdout.buffer.write(b''.join(v.read_file('{EXPORT}/bundle.json')))")))
    assert bundle['volume_path'] == EXPORT + '/results.tar'
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert shutil.disk_usage(destination.parent).free > bundle['payload_bytes'] + 1024**3
    stage.mkdir()
    download = subprocess.Popen(ssh_python(
        f"for chunk in v.read_file('{EXPORT}/results.tar'):\n sys.stdout.buffer.write(chunk)\n"),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
    extract = subprocess.Popen(['tar', '-xf', '-', '-C', str(stage),
                                '--no-same-owner', '--no-same-permissions'], stdin=subprocess.PIPE)
    received, checkpoint = 0, 0
    archive_hash = hashlib.sha256()
    try:
        while block := download.stdout.read(1024 * 1024):
            archive_hash.update(block)
            received += len(block)
            extract.stdin.write(block)
            if received - checkpoint >= 128 * 1024**2:
                print(json.dumps({'received_bytes': received, 'expected_bytes': bundle['bytes']}), flush=True)
                checkpoint = received
        extract.stdin.close()
        assert download.wait() == 0, 'SSH/Modal download failed; partial files retained'
        assert extract.wait() == 0, 'Tar extraction failed; partial files retained'
        assert received == bundle['bytes'] and archive_hash.hexdigest() == bundle['sha256']
    finally:
        for process in (download, extract):
            if process.poll() is None:
                process.terminate()
                process.wait()
    manifest_path = stage / 'transfer_manifest.json'
    assert digest(manifest_path) == bundle['manifest_sha256']
    manifest = json.loads(manifest_path.read_text())
    expected = {entry['path'] for entry in manifest['files']} | {'transfer_manifest.json'}
    actual = {str(path.relative_to(stage)) for path in stage.rglob('*') if path.is_file()}
    assert actual == expected and len(actual) == bundle['files']
    for entry in manifest['files']:
        path = stage / entry['path']
        assert path.resolve().is_relative_to(stage) and not path.is_symlink()
        assert path.stat().st_size == entry['bytes'], entry['path']
        assert digest(path) == entry['sha256'], entry['path']
    for dataset, count in [('cvbench', 997), ('mvu_eval', 1824)]:
        with (stage / 'answers' / (dataset + '.jsonl')).open() as stream:
            assert sum(1 for line in stream if line.strip()) == count
    receipt = dict(verified_at=time.time(), destination=str(destination), files_verified=len(actual),
                   archive=bundle, all_sizes_and_sha256_match=True, modal_originals_preserved=True)
    (stage / 'transfer_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    stage.rename(destination)
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == '__main__':
    main()
