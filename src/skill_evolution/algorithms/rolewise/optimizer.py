"""One-role coordinate updates, Train feedback, complete Cal/Gate comparisons."""
from pathlib import Path
import json
from mvagent.skills.bank import SkillBank
from mvagent.utils.io import write_json
from ...infra.banks import BankSnapshot, apply_edit, freeze_bank
from ...infra.llm import call_json
from ...infra.trajectory import examples
from .prompts import messages, SCHEMA


def evolve(*, client, runtime, config, evaluator, output):
    output = Path(output)
    banks = output / 'banks'
    current = freeze_bank(SkillBank.from_dict({'schema_version': 3, 'skills': []}), banks)
    accepted = 0
    # The baseline provides a full metric before any optimizer call.
    for partition in ('train', 'cal', 'gate'):
        evaluator(current, partition)
    for index in range(config.rounds):
        role = config.roles[index % len(config.roles)]
        directory = output / 'rounds' / f'{index:03d}-{role}'
        decision_path = directory / 'decision.json'
        if decision_path.exists():
            decision = json.loads(decision_path.read_text())
            if decision['parent_sha256'] != current.sha256:
                raise ValueError('Checkpoint parent does not match accepted lineage')
            current = BankSnapshot(banks / (decision['result_sha256'] + '.json'), decision['result_sha256'])
            current.load()
            accepted += decision['accepted']
            continue
        parent = current
        parent_train = evaluator(parent, 'train')
        parent_cal = evaluator(parent, 'cal')
        parent_gate = evaluator(parent, 'gate')
        trials, last_train, last_edit = [], None, None
        seen = {parent.sha256}
        for attempt in range(config.candidates_per_round):
            trial_dir = directory / f'proposal-{attempt:02d}'
            evidence = examples(parent_train, role, config, candidate=last_train, attempt=attempt)
            prompt = messages(runtime, role, parent.load(), evidence, config.max_cards_per_role, last_edit)
            try:
                edit = call_json(client, prompt, SCHEMA, trial_dir, 'role_skill_edit')
                bank = apply_edit(parent.load(), role, edit, config.max_cards_per_role)
                candidate = freeze_bank(bank, banks)
                if candidate.sha256 in seen:
                    write_json(trial_dir / 'validation.json', {'valid': True, 'evaluated': False, 'reason': 'unchanged_or_duplicate'})
                    continue
                seen.add(candidate.sha256)
                write_json(trial_dir / 'validation.json', {'valid': True, 'bank_sha256': candidate.sha256})
            except (ValueError, RuntimeError) as exc:
                write_json(trial_dir / 'validation.json', {'valid': False, 'error': str(exc)}, redact=client.api_key)
                continue
            # Infrastructure/scoring failures deliberately propagate, not become zero scores.
            train = evaluator(candidate, 'train')
            cal = evaluator(candidate, 'cal')
            write_json(trial_dir / 'evaluation.json', {'train': train.summary(), 'cal': cal.summary()})
            trials.append((candidate, cal))
            last_train, last_edit = train, edit
        eligible = [(bank, score) for bank, score in trials if score.score > parent_cal.score]
        decision = {'round': index, 'role': role, 'parent_sha256': parent.sha256,
                    'parent_cal': parent_cal.summary(), 'parent_gate': parent_gate.summary(),
                    'accepted': False, 'result_sha256': parent.sha256,
                    'reason': 'no_cal_improvement'}
        if eligible:
            candidate, cal = max(eligible, key=lambda item: item[1].score)
            gate = evaluator(candidate, 'gate')
            improved = gate.score > parent_gate.score
            decision.update(candidate_sha256=candidate.sha256, candidate_cal=cal.summary(),
                            candidate_gate=gate.summary(), accepted=improved,
                            reason='gate_improved' if improved else 'gate_not_improved',
                            result_sha256=candidate.sha256 if improved else parent.sha256)
            if improved:
                current = candidate
                accepted += 1
        write_json(decision_path, decision)
        print(json.dumps(decision), flush=True)
    final = {'status': 'completed', 'rounds': config.rounds, 'accepted_rounds': accepted,
             'bank_path': str(current.path), 'bank_sha256': current.sha256,
             'gate': evaluator(current, 'gate').summary()}
    write_json(output / 'summary.json', final)
    return final
