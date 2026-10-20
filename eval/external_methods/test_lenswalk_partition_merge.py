"""CPU-only merge regression using already-scored historical answers; no new Judge calls."""
from pathlib import Path
import math
import tempfile

from common import sha256, write
from lenswalk_partition import merge, read, partition


def same_statistics(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys()==expected.keys()
        for key, value in expected.items():
            same_statistics(actual[key], value)
    elif isinstance(expected, list):
        assert sorted(actual)==sorted(expected)
    elif isinstance(expected, float):
        assert math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
    else:
        assert actual==expected


def main():
    old = Path('/runs/devbox/lenswalk_full_35b_parallel_media_20261018')
    baseline = read(old/'summary.json')
    ids = read(old/'samples.json')
    by_id = {row['sample_id']:row for row in baseline['rows']}
    groups = partition(ids, {})
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch)/'merged'
        children = []
        for index, assigned in enumerate(groups):
            child = Path(scratch)/str(index)
            write(child/'samples.json', assigned)
            write(child/'summary.json', {'rows':[by_id[sid] for sid in assigned]})
            write(child/'progress.json', {'phase':'completed_with_errors'})
            (child/'frozen_repo').symlink_to(old/'frozen_repo', target_is_directory=True)
            children.append(dict(root=str(child), samples_sha256=sha256(child/'samples.json')))
        write(output/'samples.json', ids)
        write(output/'manifest.json', dict(model='27B', children=children, inherited_sources={}, created_at='test'))
        merge(output)
        observed = read(output/'summary.json')
        same_statistics(observed['benchmarks'], baseline['benchmarks'])
        assert len(observed['rows'])==5321
        assert read(output/'progress.json')['models'] == {'27B': {'finished': 5321}}
        # A second owner cannot silently replace an answer in the combined report.
        second = Path(children[1]['root'])
        bad = read(second/'summary.json')
        bad['rows'][0] = by_id[groups[0][0]]
        write(second/'summary.json', bad)
        try:
            merge(output)
        except AssertionError:
            pass
        else:
            raise AssertionError('Duplicate/missing ownership was accepted')
    print('Historical 5321-row aggregation exactly preserved; duplicate/missing ownership rejected; no new inference/Judge')


if __name__=='__main__':
    main()
