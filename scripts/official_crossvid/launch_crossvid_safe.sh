#!/usr/bin/env bash
# Resume-capable full CrossVid official run on GPUs 6/7 (safe concurrency).
#
# - Reuses running loopback vLLM endpoints selected by GPU6_PORT/GPU7_PORT
# - Executes the vendored upstream CrossVid task scripts without patching them
# - Runs tasks sequentially per GPU with bounded threads, 3 attempts each
# - Resumes from existing *_result.json files
#
# Usage: FRAMES=512 THREADS=1 launch_crossvid_safe.sh [OUTPUT_DIR]
set -uo pipefail

REPO=/home/kww/projects/MVAgent_API
OUTPUT=${1:-$REPO/outputs/qwen36_official_crossvid}
PYTHON=/home/kww/miniconda3/envs/MVAgent/bin/python
SOURCE=$REPO/eval/e2e_eval/CrossVid
DATA=/home/kww/datasets/Multi-Video/CrossVid
MODEL=${MODEL:-qwen35_local}
FRAMES=${FRAMES:-128}
MAX_FRAME_SIDE=${MAX_FRAME_SIDE:-${LENGTH:-360}}
THREADS=${THREADS:-1}
GPU6_PORT=${GPU6_PORT:-8100}
GPU7_PORT=${GPU7_PORT:-8001}
MEDIA_CACHE_DIR=${MEDIA_CACHE_DIR:-$REPO/.cache/e2e_media}
DECORD_EOF_RETRY_MAX=${DECORD_EOF_RETRY_MAX:-40960}
CROSSVID_MAX_TASKS_PER_CHILD=${CROSSVID_MAX_TASKS_PER_CHILD:-25}
export MVAGENT_E2E_MEDIA_CACHE_DIR="$MEDIA_CACHE_DIR"
export DECORD_EOF_RETRY_MAX
export CROSSVID_MAX_TASKS_PER_CHILD
export NO_PROXY=127.0.0.1,localhost,0.0.0.0
export no_proxy="$NO_PROXY"

for value in "$FRAMES" "$MAX_FRAME_SIDE" "$THREADS" "$GPU6_PORT" "$GPU7_PORT" \
    "$DECORD_EOF_RETRY_MAX" "$CROSSVID_MAX_TASKS_PER_CHILD"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        printf 'invalid positive integer setting: %s\n' "$value" >&2
        exit 2
    fi
done

result_count() {
    "$PYTHON" -c 'import json,sys
try: print(len(json.load(open(sys.argv[1]))))
except Exception: print(0)' "$1"
}

run_task() {
    task=$1
    port=$2
    expected=$3
    media_root=$4
    result="$OUTPUT/raw/${task}_result.json"
    log="$OUTPUT/logs/${task}_safe.log"
    for attempt in 1 2 3; do
        count=$(result_count "$result")
        if [ "$count" -ge "$expected" ]; then
            printf '%s complete: %s/%s\n' "$task" "$count" "$expected" >> "$log"
            return 0
        fi
        printf '%s attempt %s, resume %s/%s, port %s, threads %s\n' \
            "$task" "$attempt" "$count" "$expected" "$port" "$THREADS" >> "$log"
        "$PYTHON" "$SOURCE/eval/${task}.py" \
            --model "$MODEL" \
            --frames "$FRAMES" \
            --length "$MAX_FRAME_SIDE" \
            --threads "$THREADS" \
            --port "$port" \
            --video_root "$media_root" \
            --QA_path "$DATA/QA/${task}.json" \
            --save_path "$result" >> "$log" 2>&1
    done
    count=$(result_count "$result")
    printf '%s stopped incomplete: %s/%s\n' "$task" "$count" "$expected" >> "$log"
    [ "$count" -ge "$expected" ]
}

monitor_memory() {
    process_group=$(ps -o pgid= -p "$1" | tr -d ' ')
    while kill -0 "$1" 2>/dev/null; do
        timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
        available_kib=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
        process_rss_kib=$(ps -eo pgid=,rss= | awk -v group="$process_group" '$1 == group {sum += $2} END {print sum + 0}')
        printf '%s\tMemAvailableKiB=%s\tCrossVidRSSKiB=%s\n' \
            "$timestamp" "$available_kib" "$process_rss_kib" >> "$OUTPUT/logs/memory_safe.tsv"
        sleep 60
    done
}

wait_endpoint() {
    port=$1
    for attempt in $(seq 1 360); do
        if curl --noproxy '*' -fsS --max-time 2 "http://127.0.0.1:${port}/health" >/dev/null; then
            printf '%s endpoint ready: port %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$port" \
                >> "$OUTPUT/logs/launcher_safe.log"
            return 0
        fi
        sleep 10
    done
    printf '%s endpoint timeout: port %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$port" \
        >> "$OUTPUT/logs/launcher_safe.log"
    return 1
}

queue_gpu6() {
    run_task FSA "$GPU6_PORT" 2248 "$DATA/videos" || return 1
    run_task CC "$GPU6_PORT" 798 "$DATA/videos" || return 1
    run_task BU "$GPU6_PORT" 848 "$DATA/videos" || return 1
    run_task MOC "$GPU6_PORT" 566 "$DATA/uav" || return 1
}

queue_gpu7() {
    run_task NC "$GPU7_PORT" 1221 "$DATA/videos" || return 1
    run_task PEA "$GPU7_PORT" 953 "$DATA/videos" || return 1
    run_task CCQA "$GPU7_PORT" 872 "$DATA/videos" || return 1
    run_task PSS "$GPU7_PORT" 664 "$DATA/videos" || return 1
    run_task MSR "$GPU7_PORT" 594 "$DATA/uav" || return 1
    run_task PI "$GPU7_PORT" 251 "$DATA/videos" || return 1
}

mkdir -p "$OUTPUT/raw" "$OUTPUT/logs"
if [ ! -d "$SOURCE/eval" ]; then
    printf 'Vendored CrossVid evaluation source is unavailable: %s\n' "$SOURCE" >&2
    exit 2
fi

source_commit=$(git -C "$SOURCE" rev-parse HEAD 2>/dev/null || printf 'unavailable')
video2frames_sha256=$(sha256sum "$SOURCE/eval/utils/video2frames.py" | awk '{print $1}')
interval2frames_sha256=$(sha256sum "$SOURCE/eval/utils/interval2frames.py" | awk '{print $1}')
frame_bbox_sha256=$(sha256sum "$SOURCE/eval/utils/frame_bbox.py" | awk '{print $1}')
preprocess_cache_sha256=$(sha256sum "$SOURCE/eval/utils/preprocess_cache.py" | awk '{print $1}')
settings=$(printf '%s\n' \
    "model=$MODEL" \
    "frames_per_question=$FRAMES" \
    "max_frame_side=$MAX_FRAME_SIDE" \
    "workers_per_gpu=$THREADS" \
    "decord_eof_retry_max=$DECORD_EOF_RETRY_MAX" \
    "max_tasks_per_child=$CROSSVID_MAX_TASKS_PER_CHILD" \
    "gpu6_port=$GPU6_PORT" \
    "gpu7_port=$GPU7_PORT" \
    "media_cache_dir=$MEDIA_CACHE_DIR" \
    "video2frames_sha256=$video2frames_sha256" \
    "interval2frames_sha256=$interval2frames_sha256" \
    "frame_bbox_sha256=$frame_bbox_sha256" \
    "preprocess_cache_sha256=$preprocess_cache_sha256" \
    "source_commit=$source_commit" \
    "source_checkout=$SOURCE")
settings_path="$OUTPUT/run_settings.env"
if [ -f "$settings_path" ] && [ "$(cat "$settings_path")" != "$settings" ]; then
    printf 'CrossVid settings differ from existing output: %s\n' "$settings_path" >&2
    exit 2
fi
printf '%s\n' "$settings" > "$settings_path"
rm -f "$OUTPUT/inference_complete.txt"

monitor_memory "$$" & monitor_pid=$!
if ! wait_endpoint "$GPU6_PORT" || ! wait_endpoint "$GPU7_PORT"; then
    kill "$monitor_pid" 2>/dev/null || true
    wait "$monitor_pid" 2>/dev/null || true
    exit 1
fi

queue_gpu6 & queue6_pid=$!
queue_gpu7 & queue7_pid=$!

status=0
wait "$queue6_pid" || status=1
wait "$queue7_pid" || status=1
kill "$monitor_pid" 2>/dev/null || true
wait "$monitor_pid" 2>/dev/null || true

date -u '+finished_at=%Y-%m-%dT%H:%M:%SZ' > "$OUTPUT/inference_complete.txt"
printf 'status=%s\n' "$status" >> "$OUTPUT/inference_complete.txt"
exit "$status"
