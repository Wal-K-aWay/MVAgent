#!/usr/bin/env bash
# Run one non-overlapping CrossVid task lane against an existing vLLM endpoint.
#
# Usage:
#   run_crossvid_accelerator_lane.sh OUTPUT_DIR PORT LANE_NAME TASK [TASK ...]
set -uo pipefail

REPO=/home/kww/projects/MVAgent_API
OUTPUT=$1
PORT=$2
LANE=$3
shift 3

PYTHON=/home/kww/miniconda3/envs/MVAgent/bin/python
SOURCE=$REPO/eval/e2e_eval/CrossVid
DATA=/home/kww/datasets/Multi-Video/CrossVid
MODEL=${MODEL:-qwen3_5_9b}
FRAMES=${FRAMES:-512}
MAX_FRAME_SIDE=${MAX_FRAME_SIDE:-720}
THREADS=${THREADS:-1}
MEDIA_CACHE_DIR=${MEDIA_CACHE_DIR:-$REPO/.cache/e2e_media}
DECORD_EOF_RETRY_MAX=${DECORD_EOF_RETRY_MAX:-40960}
ALLOW_INCOMPLETE_TASKS=${ALLOW_INCOMPLETE_TASKS:-0}
# Some 512-frame tasks leave large Base64/JPEG arenas in a worker even after a
# request completes. Recycle aggressively so concurrent lanes cannot accumulate
# that allocator high-water mark for dozens of questions.
CROSSVID_MAX_TASKS_PER_CHILD=${CROSSVID_MAX_TASKS_PER_CHILD:-4}
export MVAGENT_E2E_MEDIA_CACHE_DIR="$MEDIA_CACHE_DIR"
export DECORD_EOF_RETRY_MAX
export CROSSVID_MAX_TASKS_PER_CHILD
export NO_PROXY=127.0.0.1,localhost,0.0.0.0
export no_proxy="$NO_PROXY"

declare -A EXPECTED=(
    [FSA]=2248 [CC]=798 [BU]=848 [MOC]=566
    [NC]=1221 [PEA]=953 [CCQA]=872 [PSS]=664 [MSR]=594 [PI]=251
)

if [ "$ALLOW_INCOMPLETE_TASKS" != 0 ] && [ "$ALLOW_INCOMPLETE_TASKS" != 1 ]; then
    printf 'ALLOW_INCOMPLETE_TASKS must be 0 or 1\n' >&2
    exit 2
fi

result_count() {
    "$PYTHON" -c 'import json,sys
try: print(len(json.load(open(sys.argv[1]))))
except Exception: print(0)' "$1"
}

run_task() {
    task=$1
    expected=${EXPECTED[$task]}
    media_root=$DATA/videos
    if [ "$task" = MOC ] || [ "$task" = MSR ]; then
        media_root=$DATA/uav
    fi
    result="$OUTPUT/raw/${task}_result.json"
    log="$OUTPUT/logs/${task}_safe.log"
    for attempt in 1 2 3; do
        count=$(result_count "$result")
        if [ "$count" -ge "$expected" ]; then
            printf '%s accelerator complete: %s/%s\n' "$task" "$count" "$expected" >> "$log"
            return 0
        fi
        printf '%s accelerator lane=%s attempt=%s resume=%s/%s port=%s threads=%s\n' \
            "$task" "$LANE" "$attempt" "$count" "$expected" "$PORT" "$THREADS" >> "$log"
        "$PYTHON" "$SOURCE/eval/${task}.py" \
            --model "$MODEL" \
            --frames "$FRAMES" \
            --length "$MAX_FRAME_SIDE" \
            --threads "$THREADS" \
            --port "$PORT" \
            --video_root "$media_root" \
            --QA_path "$DATA/QA/${task}.json" \
            --save_path "$result" >> "$log" 2>&1
    done
    count=$(result_count "$result")
    printf '%s accelerator stopped incomplete: %s/%s\n' "$task" "$count" "$expected" >> "$log"
    if [ "$count" -ge "$expected" ]; then
        return 0
    fi
    if [ "$ALLOW_INCOMPLETE_TASKS" = 1 ]; then
        printf '%s accelerator skipped missing samples: %s/%s; continuing lane=%s\n' \
            "$task" "$count" "$expected" "$LANE" >> "$log"
        return 0
    fi
    return 1
}

mkdir -p "$OUTPUT/raw" "$OUTPUT/logs"
if [ "$#" -lt 1 ]; then
    printf 'at least one task is required\n' >&2
    exit 2
fi
for task in "$@"; do
    if [ -z "${EXPECTED[$task]+set}" ]; then
        printf 'unsupported CrossVid task: %s\n' "$task" >&2
        exit 2
    fi
done
if ! curl --noproxy '*' -fsS --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null; then
    printf 'vLLM endpoint is unavailable on port %s\n' "$PORT" >&2
    exit 1
fi

printf '%s\tlane=%s\tport=%s\tmodel=%s\ttasks=%s\tframes=%s\tmax_side=%s\tmax_tasks_per_child=%s\tdecord_eof_retry_max=%s\tallow_incomplete_tasks=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$LANE" "$PORT" "$MODEL" "$*" "$FRAMES" \
    "$MAX_FRAME_SIDE" "$CROSSVID_MAX_TASKS_PER_CHILD" "$DECORD_EOF_RETRY_MAX" \
    "$ALLOW_INCOMPLETE_TASKS" \
    >> "$OUTPUT/logs/accelerator_history.tsv"

for task in "$@"; do
    run_task "$task" || exit 1
done

printf '%s\tlane=%s\tstatus=complete\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$LANE" \
    >> "$OUTPUT/logs/accelerator_history.tsv"
