"""Run only the two fixed shards of the enlarged concise-Global experiment."""
import sys
import watch_system_ablation as lifecycle

lifecycle.TAG = 'global_short_large_20261017'
lifecycle.ARMS = ('shard0', 'shard1')
lifecycle.HOURS = 12
lifecycle.MAX_SECONDS = int(11.5 * 3600)
lifecycle.NAMES = {s:f'mvagent-global-short-large-20261017-{s}' for s in lifecycle.ARMS}
lifecycle.PROGRESS = {s:f'{s}/global_short/progress.json' for s in lifecycle.ARMS}
lifecycle.ANALYSIS_SCRIPT = 'run_global_short_large.py'
lifecycle.WORKERS = {
    s:('mkdir -p /work/global-short-driver && '
       f'tar xzf /runs/devbox/{lifecycle.TAG}/source.tar.gz -C /work/global-short-driver && '
       f'python /work/global-short-driver/scripts/run_global_short_large.py worker --shard {i}')
    for i,s in enumerate(lifecycle.ARMS)
}

if __name__ == '__main__':
    if '--self-check' in sys.argv:
        assert len(set(lifecycle.NAMES.values())) == 2
        assert all(f'--shard {i}' in lifecycle.WORKERS[s] for i,s in enumerate(lifecycle.ARMS))
        assert lifecycle.finished_or_expired('completed', True, 1)
        assert lifecycle.finished_or_expired('inference', False, 1)
        assert lifecycle.finished_or_expired('inference', True, 41401)
        assert not lifecycle.finished_or_expired('inference', True, 40000)
        print('Fixed-shard lifecycle checks passed')
    else:
        lifecycle.main()
