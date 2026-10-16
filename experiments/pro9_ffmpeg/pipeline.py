"""Run one eight-card Actor panel, then judge its saved open answers."""
from pathlib import Path
from types import SimpleNamespace
import judge
import run


def main():
    assert run.SHARDS==1, 'This pipeline is for the new 27B/35B single-shard runs.'
    state=run.ROOT/'pipeline_progress.json'
    try:
        run.write(state,dict(phase='actor',at=run.now(),pipeline_sha256=run.sha(__file__)))
        run.serve(SimpleNamespace(shard=0))
        run.write(state,dict(phase='judge',at=run.now()))
        judge.judge()
        run.write(state,dict(phase='judge_completed',at=run.now()))
    except BaseException as exc:
        run.write(state,dict(phase='failed',at=run.now(),error=repr(exc)))
        raise
    finally:
        (Path('/work/jobs')/f'{run.ROOT.name}_pipeline.pid').unlink(missing_ok=True)


if __name__=='__main__':main()
