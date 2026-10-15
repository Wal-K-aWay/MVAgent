#!/usr/bin/env bash
# Historical compatibility launcher using the vendored upstream evaluation sources
# documented in eval/README.md.
set -uo pipefail

REPO=/home/kww/projects/MVAgent_API
PYTHON=/home/kww/miniconda3/envs/MVAgent/bin/python
OUTPUT=${1:-$REPO/outputs/full_3benchmark_end_to_end_512_20260821}
CV_SOURCE=$REPO/eval/e2e_eval/CVBench
MVU_SOURCE=$REPO/eval/e2e_eval/MVU-Eval
CV_PORT=8100
MVU_PORT=8001

mkdir -p "$OUTPUT/logs"
printf 'started_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$OUTPUT/run_status.env"
printf 'phase=direct_cvbench_mvu\n' >> "$OUTPUT/run_status.env"

cd "$REPO" || exit 1
PYTHONPATH=src "$PYTHON" scripts/run_official_cvbench_mvu.py \
    --output "$OUTPUT/cvbench" \
    --cvbench-source "$CV_SOURCE" \
    --mvu-source "$MVU_SOURCE" \
    --only cvbench \
    --cv-ports "$CV_PORT" \
    --mvu-ports "$MVU_PORT" \
    --cv-workers 1 \
    --cv-frames-per-video 256 \
    --cv-question-frame-cap 512 \
    --api-timeout 600 \
    --max-retries 3 > "$OUTPUT/logs/cvbench.log" 2>&1 &
cv_pid=$!

PYTHONPATH=src "$PYTHON" scripts/run_official_cvbench_mvu.py \
    --output "$OUTPUT/mvu_eval" \
    --cvbench-source "$CV_SOURCE" \
    --mvu-source "$MVU_SOURCE" \
    --only mvu-eval \
    --cv-ports "$CV_PORT" \
    --mvu-ports "$MVU_PORT" \
    --mvu-workers-per-port 1 \
    --mvu-frames-per-video 512 \
    --mvu-question-frame-cap 512 \
    --mvu-max-side 720 \
    --mvu-max-tokens 64 \
    --no-mvu-enable-thinking \
    --api-timeout 600 \
    --max-retries 3 > "$OUTPUT/logs/mvu_eval.log" 2>&1 &
mvu_pid=$!

cv_status=0
mvu_status=0
wait "$cv_pid" || cv_status=$?
wait "$mvu_pid" || mvu_status=$?
printf 'cvbench_status=%s\n' "$cv_status" >> "$OUTPUT/run_status.env"
printf 'mvu_eval_status=%s\n' "$mvu_status" >> "$OUTPUT/run_status.env"

printf 'phase=crossvid\n' >> "$OUTPUT/run_status.env"
FRAMES=512 \
MAX_FRAME_SIDE=360 \
THREADS=1 \
GPU6_PORT="$CV_PORT" \
GPU7_PORT="$MVU_PORT" \
bash scripts/official_crossvid/launch_crossvid_safe.sh "$OUTPUT/crossvid" \
    > "$OUTPUT/logs/crossvid_launcher.log" 2>&1
crossvid_status=$?
printf 'crossvid_status=%s\n' "$crossvid_status" >> "$OUTPUT/run_status.env"
printf 'finished_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> "$OUTPUT/run_status.env"

if [ "$cv_status" -ne 0 ] || [ "$mvu_status" -ne 0 ] || [ "$crossvid_status" -ne 0 ]; then
    printf 'status=1\n' >> "$OUTPUT/run_status.env"
    exit 1
fi
printf 'status=0\n' >> "$OUTPUT/run_status.env"
