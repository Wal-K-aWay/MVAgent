#!/usr/bin/env bash
# Monitor and fail-safe only the optional accelerator lanes. The primary benchmark
# process is never terminated by this guard, and every accelerator output is resumable.
set -uo pipefail

OUTPUT=$1
INTERVAL_SECONDS=${INTERVAL_SECONDS:-60}
MIN_AVAILABLE_GIB=${MIN_AVAILABLE_GIB:-256}
# This is an aggregate emergency ceiling across all accelerator lanes. Normal
# memory control comes from the short per-child lifetime; MemAvailable remains
# the authoritative whole-system guard (and includes vLLM and filesystem cache).
MAX_ACCELERATOR_RSS_GIB=${MAX_ACCELERATOR_RSS_GIB:-64}
LOG=$OUTPUT/logs/accelerator_resources.tsv

for value in "$INTERVAL_SECONDS" "$MIN_AVAILABLE_GIB" "$MAX_ACCELERATOR_RSS_GIB"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        printf 'invalid positive integer setting: %s\n' "$value" >&2
        exit 2
    fi
done

mkdir -p "$OUTPUT/logs"
if [ ! -s "$LOG" ]; then
    printf 'timestamp\tmem_available_kib\taccelerator_rss_kib\tcrossvid_rss_kib\tvllm_rss_kib\tgpu4_util\tgpu4_mem_mib\tgpu5_util\tgpu5_mem_mib\taction\n' > "$LOG"
fi

min_available_kib=$((MIN_AVAILABLE_GIB * 1024 * 1024))
max_accelerator_rss_kib=$((MAX_ACCELERATOR_RSS_GIB * 1024 * 1024))

while true; do
    groups=$(ps -eo pgid=,comm=,args= | awk \
        '$2 == "bash" && $0 ~ /run_crossvid_accelerator_lane[.]sh/ {print $1}' | sort -u)
    if [ -z "$groups" ]; then
        exit 0
    fi

    accelerator_rss_kib=$(ps -eo pgid=,rss= | awk -v groups="$groups" '
        BEGIN {split(groups, values, /[[:space:]]+/); for (i in values) wanted[values[i]]=1}
        $1 in wanted {sum += $2}
        END {print sum + 0}')
    crossvid_rss_kib=$(ps -eo rss=,args= | awk -v output="$OUTPUT" \
        '$0 ~ /CrossVid\/eval\// && index($0, output) {sum += $1} END {print sum + 0}')
    vllm_rss_kib=$(ps -eo rss=,args= | awk \
        '$0 ~ /vllm serve/ && ($0 ~ /--port 8101/ || $0 ~ /--port 8102/) {sum += $1} END {print sum + 0}')
    available_kib=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    gpu_values=$(nvidia-smi --query-gpu=index,utilization.gpu,memory.used \
        --format=csv,noheader,nounits -i 4,5 | tr -d ' ')
    gpu4=$(printf '%s\n' "$gpu_values" | awk -F, '$1 == 4 {print $2 "\t" $3}')
    gpu5=$(printf '%s\n' "$gpu_values" | awk -F, '$1 == 5 {print $2 "\t" $3}')
    action=continue
    if [ "$available_kib" -lt "$min_available_kib" ] || \
        [ "$accelerator_rss_kib" -gt "$max_accelerator_rss_kib" ]; then
        action=stop_accelerators
    fi
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$available_kib" \
        "$accelerator_rss_kib" "$crossvid_rss_kib" "$vllm_rss_kib" \
        "$gpu4" "$gpu5" "$action" >> "$LOG"

    if [ "$action" = stop_accelerators ]; then
        for group in $groups; do
            if [[ "$group" =~ ^[1-9][0-9]*$ ]]; then
                kill -TERM -- "-$group" 2>/dev/null || true
            fi
        done
        exit 1
    fi
    sleep "$INTERVAL_SECONDS"
done
