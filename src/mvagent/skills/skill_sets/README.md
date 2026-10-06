# MVAgent SkillSets

Each version directory is one immutable pair of Global and Video decision policies:

```text
skill_sets/
├── authored-v000/
│   ├── global.md
│   └── video.md
├── zero-v001/
│   ├── global.md
│   └── video.md
└── zero-v002/
    ├── global.md
    └── video.md
```

- `authored-v000` is the single human- or LLM-authored comparison SkillSet. It is
  frozen and is not the initialization of the primary self-evolution run.
- The primary self-evolution lineage starts with both role Skills empty. Its generation
  zero is represented by the existing No-Skill configuration, not by empty source
  files. `zero-v001`, `zero-v002`, and later versions are created only for non-empty
  optimizer-produced SkillSets that pass the MVAgent promotion gate.
- If a later experiment evolves from the authored comparison, use a separate
  `authored-v001`, `authored-v002`, ... lineage. Never mix its version numbers with
  the zero-initialized lineage. A promoted version is never edited in place.
- `global.md` and `video.md` contain policy text only. Their common parent directory is
  the SkillSet identity; runnable configurations freeze both exact paths and SHA256 values.
- A cycle that changes only one role still copies the unchanged partner into the new
  version, so each SkillSet is self-contained and reversible.
- Raw candidates, checkpoints, rewards, and rejected variants stay under
  `outputs/mvagent/skill/skill_evolution/<run_id>/`; they never enter this source directory.
- There is no mutable `best`, `latest`, or overwritten `best_skill.md`. The selected
  version is always explicit in configuration.
- No-Skill disables both role references and does not use placeholder files.

The first system comparison uses No-Skill, `authored-v000`, and the latest promoted
`zero-vNNN` as three complete conditions. No-Skill is a fixed inference control;
zero-init generation zero has the same runtime behavior but continues into offline
optimization. Later role ablations reuse the same version directory and disable one
role without creating another Skill copy.

The shipped Skill-on YAML files currently reference `authored-v000`, while
`configs/inference/local_qwen35_vllm_no_skill.yaml` is the explicit No-Skill control. Do not add a
`zero-vNNN` runtime configuration until that exact non-empty SkillSet exists and its two
file hashes are frozen; promotion should generate that configuration from the accepted
candidate rather than relying on a mutable `best` path.

`dynamic-v003/` adds the hash-pinned JSON snapshot of the seven existing handwritten
`authored/dynamic-v003` cards for the optional27B+embedding configuration. Contents
are identical to the completed35B diagnostic bank; no new strategy is introduced.
