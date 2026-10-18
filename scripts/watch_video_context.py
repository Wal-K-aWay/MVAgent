"""Own only the two independent Video context candidate Sandboxes."""
import sys
import watch_system_ablation as lifecycle

lifecycle.TAG='video_context_20261018'
lifecycle.ARMS=('boundary_only','with_question')
lifecycle.HOURS=3
lifecycle.MAX_SECONDS=9900
lifecycle.NAMES={a:f'mvagent-video-context-20261018-{a}' for a in lifecycle.ARMS}
lifecycle.PROGRESS={a:f'{a}/progress.json' for a in lifecycle.ARMS}
lifecycle.ANALYSIS_SCRIPT='run_video_context.py'
lifecycle.WORKERS={a:('mkdir -p /work/video-context-driver && '
    f'tar xzf /runs/devbox/{lifecycle.TAG}/source.tar.gz -C /work/video-context-driver && '
    f'python /work/video-context-driver/scripts/run_video_context.py worker --arm {a}') for a in lifecycle.ARMS}

if __name__=='__main__':
    if '--self-check' in sys.argv:
        assert len(set(lifecycle.NAMES.values()))==2
        assert all(f'--arm {a}' in lifecycle.WORKERS[a] for a in lifecycle.ARMS)
        assert lifecycle.finished_or_expired('inference',True,9901)
        assert not lifecycle.finished_or_expired('inference',True,9800)
        print('Video candidate lifecycle checks passed')
    else:lifecycle.main()
