"""The follow-up must never submit a GPU before the existing run has finished."""
from watch_lenswalk_media_retry import primary_finished

for phase in ('prepared', 'starting_models', 'inference', 'judging', 'scoring'):
    assert not primary_finished(phase)
for phase in ('completed', 'completed_with_errors'):
    assert primary_finished(phase)
for phase in ('failed', 'interrupted'):
    try:
        primary_finished(phase)
    except RuntimeError:
        pass
    else:
        raise AssertionError('An interrupted or failed primary run was allowed to launch a retry')
print('Wait for inference and Judge; reject failed/interrupted primary; allow completed runs')
