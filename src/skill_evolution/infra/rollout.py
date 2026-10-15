"""Candidate Skill and cache adapter over MVAgent's public batch executor."""
from copy import deepcopy
import json
from pathlib import Path
import time
import threading
import yaml
from mvagent.batch import BatchExecutor
from mvagent.utils import mask_sensitive_data
from .data import RolloutArtifact
from .skills import Role
from .store import JsonEpisodeCache, write_json


def collect_rollouts(executor, cache, request):
    """Shared cache path for algorithm adapters and independent evaluation."""
    from dataclasses import replace
    if getattr(executor, "cache", None) is cache:
        return executor.execute(request)
    found = {sid: cache[request.context.rollout_cache_key(request.skill_set, sid)]
             for sid in request.sample_ids
             if request.context.rollout_cache_key(request.skill_set, sid) in cache}
    missing = tuple(sid for sid in request.sample_ids if sid not in found)
    if missing:
        generated = executor.execute(replace(request, sample_ids=missing))
        if len(generated) != len(missing) or {e.sample_id for e in generated} != set(missing):
            raise ValueError("Rollout executor returned duplicate, missing, or unexpected samples")
        for episode in generated:
            found[episode.sample_id] = episode
            cache[request.context.rollout_cache_key(request.skill_set, episode.sample_id)] = episode
    return tuple(found[sid] for sid in request.sample_ids)


class FrozenMVAgentExecutor:
    def __init__(self, *, records, output_dir, base_config_path, runtime_snapshot_sha256,
                 execution_config, cache_dir=None, base_config=None, batch_executor=None):
        self.records = records
        self.output_dir = Path(output_dir)
        self.base_config = deepcopy(base_config) if base_config is not None else yaml.safe_load(Path(base_config_path).read_text())
        self.runtime_snapshot_sha256 = runtime_snapshot_sha256
        self.cache = JsonEpisodeCache(Path(cache_dir or self.output_dir / "cache") / "rollouts")
        self.batch = batch_executor or BatchExecutor(execution_config, on_event=self._event)
        self.on_complete = None
        self.last_generated = 0
        self._execute_lock = threading.Lock()

    def close(self):
        self.batch.close()

    def _config(self, pair):
        directory = self.output_dir / "skills" / pair.skill_set_hash()
        path = directory / "config.yaml"
        directory.mkdir(parents=True, exist_ok=True)
        config = deepcopy(self.base_config)
        for role in Role:
            text = pair.get(role)
            skill_path = directory / f"{role.value}.md"
            skill_path.write_text(text)
            config["agents"][role.value + "_agent"]["skill"] = (
                {"enabled": True, "path": str(skill_path.resolve()), "sha256": pair.skill_sha256(role)}
                if text else {"enabled": False})
        path.write_text(yaml.safe_dump(mask_sensitive_data(config), sort_keys=False))
        write_json(directory / "skill_set.json", pair.to_dict())
        return str(path.resolve()), config

    def _event(self, event):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with (self.output_dir / "rollout_events.jsonl").open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    def execute(self, request, on_complete=None):
        with self._execute_lock:
            return self._execute(request, on_complete or self.on_complete)

    def _execute(self, request, on_complete):
        if len(set(request.sample_ids)) != len(request.sample_ids):
            raise ValueError("Rollout sample IDs must be unique")
        _, config_data = self._config(request.skill_set)
        found, pending = {}, []
        for sid in request.sample_ids:
            cached = self.cache.get(request.context.rollout_cache_key(request.skill_set, sid))
            if cached is not None:
                found[sid] = cached
                self._event(dict(time=time.time(), kind="question_reused", sample_id=sid))
                if on_complete:
                    on_complete(cached)
            else:
                sample = self.records[sid].sample
                pending.append(dict(sample_id=sid, question=sample.question, videos=dict(sample.videos)))
        self.last_generated = len(pending)

        def completed(payload):
            sid = payload["sample_id"]
            if payload["status"] != "ok":
                write_json(self.output_dir / "failures" / (sid.replace("/", "_") + ".json"), payload)
                return
            result = payload["result"]
            key = request.context.rollout_cache_key(request.skill_set, sid)
            artifact = RolloutArtifact(sid, {"sample_id": sid,
                "prediction": str(result.get("answer", {}).get("answer", "")), "result": result,
                "events": payload["events"], "execution": {"cache_key": key,
                    "pair_hash": request.skill_set.skill_set_hash(), "worker_pid": payload["worker_pid"],
                    "runtime_hash": self.runtime_snapshot_sha256, "repeat_id": request.context.repeat_id}},
                bucket=f"{self.records[sid].dataset}/{self.records[sid].native_task}")
            self.cache[key] = artifact
            found[sid] = artifact
            if on_complete:
                on_complete(artifact)

        self.batch.run(pending, config_data, on_complete=completed)
        return tuple(found[sid] for sid in request.sample_ids)
