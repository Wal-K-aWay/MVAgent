"""Exercise idle-node recovery without submitting jobs or touching real processes."""
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

with patch.dict(sys.modules, {'modal': Mock()}):
    import expand_external27 as control


def main():
    receipt = iter([json.dumps({'inference_retries': 0}).encode()])
    volume = SimpleNamespace(read_file=Mock(side_effect=[FileNotFoundError(), receipt, iter([b'{"inference_retries":0}'])]))
    with patch.object(control.modal.Volume, 'from_name', return_value=volume), \
         patch.object(control.time, 'sleep') as sleep:
        control.wait_for_drained('old')
    assert volume.read_file.call_count == 3 and sleep.call_count == 1
    with TemporaryDirectory() as directory:
        root = Path(directory)
        old_paths = [root/'old0.json', root/'old1.json']
        for path in old_paths:
            path.write_text('{}')
        new = 'rsi_27b_32gpu_20261020'
        targets = [root/('state-mvagent-'+(new+'-shard'+str(i)).replace('_', '-')+'.json') for i in (0, 1)]
        targets[0].write_text('{"sandbox_id":"replacement"}')
        dead = SimpleNamespace(object_id='expired', poll=lambda: 0)
        live = SimpleNamespace(object_id='live', poll=lambda: None)
        replacement = SimpleNamespace(object_id='replacement', poll=lambda: None)
        states = {
            'python-shard0': (old_paths[0], {'sandbox_id': 'expired'}, dead),
            'python-shard1': (old_paths[1], {'sandbox_id': 'live'}, live),
            new+'-shard0': (targets[0], {'sandbox_id': 'replacement'}, replacement),
        }
        owners = []
        for i in range(3):
            path = root/f'owner{i}.pid'
            path.write_text(str(os.getpid()))
            owners.append((path, os.getpid()))
        manifest = json.dumps({'model': '27B', 'total_gpus': 32}).encode()
        volume = SimpleNamespace(read_file=lambda _: iter([manifest]))
        with patch.multiple(control, BASE=root, HERE=root, PREVIOUS={'rsi': 'python'}), \
             patch.object(control, 'state', side_effect=lambda name: states[name]), \
             patch.object(control, 'owner', side_effect=owners), \
             patch.object(control, 'execute') as execute, \
             patch.object(control.modal.Volume, 'from_name', return_value=volume), \
             patch.object(control.os, 'kill') as kill, \
             patch.object(control.subprocess, 'Popen', return_value=SimpleNamespace(pid=12345)) as launch:
            control.finish('rsi')
        assert [call.args[0] for call in execute.call_args_list] == [replacement, live]
        assert json.loads(targets[0].read_text())['sandbox_id'] == 'replacement'
        assert json.loads(targets[1].read_text())['sandbox_id'] == 'live'
        assert all(not path.exists() for path in old_paths)
        assert kill.call_count == 3 and launch.call_count == 1
        assert (root/'rsi-master.pid').read_text() == '12345'
    print('Expired node skipped, replacement identity retained, one new owner launched')


if __name__ == '__main__':
    main()
