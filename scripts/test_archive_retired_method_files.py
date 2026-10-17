from pathlib import Path
import tempfile
import os
import tarfile

from archive_retired_method_files import archive_tree

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory); source = root/'retired'; source.mkdir()
    (source/'nested').mkdir()
    (source/'nested/raw.json').write_bytes(b'{"answer":"original"}\n')
    os.link(source/'nested/raw.json', source/'same_bytes')
    (source/'reference').symlink_to('nested/raw.json')
    committed = []
    def commit():
        committed.append(source.exists())
    result = archive_tree(source, root/'retired.tar', commit)
    assert committed == [True, False] and not source.exists()
    restored = root/'restored'; restored.mkdir()
    with tarfile.open(result['archive'], 'r:') as stream:
        stream.extractall(restored, filter='data')
    assert (restored/'retired/nested/raw.json').read_bytes() == b'{"answer":"original"}\n'
    assert (restored/'retired/same_bytes').read_bytes() == b'{"answer":"original"}\n'
    assert os.readlink(restored/'retired/reference') == 'nested/raw.json'
    assert result['files'] == 2
print('Uncompressed archive preserves files, hard links and symlinks; commits before removal')
