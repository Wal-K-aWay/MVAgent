#!/usr/bin/env bash
# Start the fixed CCQA judge (Qwen3-30B-A3B-Instruct-2507) on vLLM, one replica per listed GPU
# (replica i on port BASE_PORT+i), and wait until every replica answers /v1/models.
#   serve_ccqa_judge.sh [GPUS: 0 | 0,1 | 0-7 (default 0)] [BASE_PORT (default 8100)]
# Then score with: score_crossvid_ccqa.py --endpoints 8100-8107 (MVAgent) or
# `--generation-config vllm` keeps the model's generation_config.json from overriding the official sampling.
set -euo pipefail
GPUS=${1:-0}
PORT=${2:-8100}
WEIGHTS=${JUDGE_WEIGHTS:-/weights/Qwen3-30B-A3B-Instruct-2507}
LOGS=${JUDGE_LOG_DIR:-.cache/ccqa_judge}
case $GPUS in *-*) GPUS=$(seq -s, "${GPUS%-*}" "${GPUS#*-}") ;; esac
mkdir -p "$LOGS"
count=0
for gpu in ${GPUS//,/ }; do
  port=$((PORT + count))
  CUDA_VISIBLE_DEVICES=$gpu nohup vllm serve "$WEIGHTS" --served-model-name Qwen3-30B-A3B-Instruct-2507 \
    --host 127.0.0.1 --port "$port" --max-model-len 32768 --gpu-memory-utilization 0.9 \
    --generation-config vllm > "$LOGS/vllm_$port.log" 2>&1 &
  count=$((count + 1))
done
python3 - "$PORT" "$count" <<'PY'
import sys, time, urllib.request

first, count = int(sys.argv[1]), int(sys.argv[2])
pending, deadline = set(range(first, first + count)), time.time() + 1200
while pending and time.time() < deadline:
    for port in sorted(pending):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=3)
            pending.discard(port)
        except Exception:
            pass
    time.sleep(5)
sys.exit(f"judge replicas not up after 20 min: {sorted(pending)}" if pending else 0)
PY
echo "CCQA judge up on ports $PORT-$((PORT + count - 1))"
