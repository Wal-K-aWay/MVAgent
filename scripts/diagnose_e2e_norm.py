#!/usr/bin/env python3
"""Isolate shape-history effects in the RMSNorm used by Qwen3.5."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert args.input.is_relative_to('/runs') and args.output.is_relative_to('/runs')
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output/'source.py')
    os.environ.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    import torch
    from vllm.model_executor.layers.layernorm import GemmaRMSNorm
    capsule = torch.load(args.input, map_location='cuda', weights_only=True)
    x, weight, eps = (capsule[k] for k in ['x', 'weight', 'eps'])
    assert x.ndim == 2 and x.shape[0] > 32

    def sha(tensor):
        data = tensor.detach().contiguous().cpu().view(torch.uint8).numpy().tobytes()
        return hashlib.sha256(data).hexdigest()

    before = dict(x=sha(x), weight=sha(weight))
    native = GemmaRMSNorm._forward_static_no_residual
    profiles = ['compiled_auto', 'native', 'compiled_static', 'compiled_dynamic', 'compiled_auto_restored']
    results = []
    with torch.inference_mode():
        for profile in profiles:
            torch.compiler.reset()
            fn = native if profile == 'native' else torch.compile(native,
                dynamic={'compiled_static': False, 'compiled_dynamic': True}.get(profile))
            reference = None
            # Repeat A, insert a different length B, then return to exactly A.
            for index, length in enumerate([len(x), len(x), len(x)//2+7, len(x), 1, len(x)]):
                value = fn(weight, eps, x if length == len(x) else x[:length].clone())
                torch.cuda.synchronize()
                row = dict(profile=profile, index=index, length=length, sha256=sha(value))
                if length == len(x):
                    if reference is None:
                        reference = value.clone()
                    row.update(changed_values=int(torch.count_nonzero(value != reference)),
                        max_absolute_difference=float((value.float()-reference.float()).abs().max()))
                results.append(row)
                print(json.dumps(row), flush=True)
                (args.output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
                del value
            del fn, reference
    assert before == dict(x=sha(x), weight=sha(weight)), 'RMSNorm mutated inputs'
    (args.output/'manifest.json').write_text(json.dumps(dict(input=str(args.input), inputs=before,
        shape=list(x.shape), eps=eps, torch=torch.__version__, gpu=torch.cuda.get_device_name(),
        gpu_uuid=str(torch.cuda.get_device_properties(0).uuid)), indent=2)+'\n')
    assert all(r.get('changed_values', 0) == 0 for r in results if r['profile'] == 'native')


if __name__ == '__main__':
    main()
