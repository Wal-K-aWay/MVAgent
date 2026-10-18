"""Small comparison/cleanup regressions, run remotely before the actual A/B."""
from pathlib import Path
import tempfile
from temp_media_probe import bytes_used,peak_usage
from temp_media_run import compare


def main():
    a=dict(prompt_token_ids=[1,2],image_sha256='frameA',token_ids=[3,4],wire_sha256='wireA')
    b=dict(a,image_sha256='frameB')
    same=compare([a],[dict(a,wire_sha256='wireB')])
    assert same['ordered_model_calls_equal'] and not same['raw_wire_hashes_equal']
    assert compare([a],[b])['first_ordered_mismatch']==0
    assert compare([a],[dict(a,token_ids=[3,5])])['first_ordered_mismatch']==0
    assert compare([a],[a,a])['first_ordered_mismatch']==1
    swapped=compare([a,b],[b,a])
    assert not swapped['ordered_model_calls_equal'] and swapped['model_call_multisets_equal']
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        with peak_usage([root]) as peak:
            (root/'file').write_bytes(b'0123456789')
        assert bytes_used(root)==10 and peak['total']==10
    assert not root.exists()
    print('Frame/token differences, transport IDs, callback-order differences and temporary cleanup checks passed')


if __name__=='__main__':main()
