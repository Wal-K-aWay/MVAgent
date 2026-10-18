"""Keep one question's unchanged concatenated input until its client has stopped."""
from contextlib import contextmanager
from pathlib import Path
import shutil
import tempfile

from common import write

LOCAL_ROOT = Path('/work')


@contextmanager
def temporary_item(prepare_item, record, attempt, lock):
    with tempfile.TemporaryDirectory(prefix='external-media-', dir=LOCAL_ROOT) as scratch:
        directory = Path(scratch)
        try:
            item = prepare_item(directory, record, lock)
            import json
            payload = json.loads(item.read_text())
            video = Path(payload['video_path'])
            shutil.copy2(item, attempt/'item.json')
            shutil.copy2(video.parent/'timeline.json', attempt/'timeline.json')
            write(attempt/'media_storage.json', dict(video_bytes=video.stat().st_size,
                  location='container-local temporary disk', lifetime='one complete question'))
            yield item
        finally:
            # The caller stops its client before exiting this context, including on interruption.
            shutil.rmtree(directory)
            write(attempt/'media_cleanup.json', dict(path=str(directory), removed=not directory.exists()))
