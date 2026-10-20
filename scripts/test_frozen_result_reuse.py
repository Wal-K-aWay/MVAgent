"""CPU-only check that Judge reuse rejects incomplete reports and preserves sources."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import finalize_frozen_results as export


def main():
    export.self_check()
    with tempfile.TemporaryDirectory() as tmp:
        run, out = Path(tmp)/'run', Path(tmp)/'out'
        parts = [[f'crossvid:CCQA:{i}' for i in range(107)],
                 [f'crossvid:CCQA:{i}' for i in range(107, 189)]]
        export.write(run/'selection.json', dict(partitions=parts))
        paths = [run/f'shard{i}'/'35B-A3B'/export.REPORT for i in range(2)]
        for path, ids in zip(paths, parts):
            export.write(path, dict(failed_ids=[], samples=[
                dict(id=int(s.rsplit(':', 1)[1]), status='ok') for s in ids]))
        digests = [export.sha(p) for p in paths]
        with patch.multiple(export, RUN=run, OUT=out, MODEL='35B-A3B'):
            export.reuse_judge()
            receipt = json.loads((out/'judge_complete.json').read_text())
            assert receipt['reused'] and receipt['shards'] == [107, 82]
            assert [export.sha(p) for p in paths] == digests
        broken = export.read(paths[1])
        broken['samples'].pop()
        export.write(paths[1], broken)
        with patch.multiple(export, RUN=run, OUT=Path(tmp)/'bad', MODEL='35B-A3B'):
            try:
                export.reuse_judge()
            except AssertionError:
                pass
            else:
                raise AssertionError('An incomplete Judge report was accepted')
            assert not export.OUT.exists()
    print('JUDGE_REUSE_CHECK_PASSED')


if __name__ == '__main__':
    main()
