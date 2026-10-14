"""Render the exact common question and upstream prompt templates without model calls."""
import argparse
import importlib.util
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--item', type=Path, required=True)
    parser.add_argument('--sources', type=Path, required=True, help='Patched external_sources in the frozen run')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    item = json.loads(args.item.read_text())
    module_path = args.sources/'Visual-Agentic-Memory/vam/prompts.py'
    spec = importlib.util.spec_from_file_location('vam_prompts_preview', module_path)
    prompts = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prompts)
    user = prompts.agent_planner_user(
        goal=item['question']+'\n\nRecent chat history:\n<runtime chat history>',
        context='<runtime retrieved evidence>', remaining_turns='<runtime remaining turns>',
        available_summary_structures='<runtime memory summary structures>')
    rsi_system = (args.sources/'Video-RSI/artifacts/final_harness/prompt.md').read_text()
    rsi_payload = dict(item=item, tools='<runtime tool descriptions>', observations='<runtime observations>',
                       step='<runtime step>', remaining_steps='<runtime remaining steps>',
                       observed_windows='<runtime observed windows>')
    sections = [
        '# Input and prompt preview',
        'The common question below is the exact prepared input. System prompts come from the frozen, '
        'patched upstream source. Fields marked <runtime ...> are templates for live evidence and '
        'state, not fabricated model outputs. No model is called by this preview.',
        f'Sample: `{item["sample_id"]}`. No answer label is included.',
        '## Shared question\n\n```text\n'+item['question']+'\n```',
        '## Video-RSI system prompt\n\n```text\n'+rsi_system+'\n```',
        'Matching skills from skill_policy.py are appended to this system prompt at each decision.',
        '## Video-RSI decision user payload\n\n```json\n'+json.dumps(rsi_payload,indent=2,ensure_ascii=False)+'\n```',
        'Its visual calls separately contain the question and observation goal, followed by alternating '
        'timestamp_seconds text and image_url parts. Actual image bytes are saved in the run request audit.',
        '## VAM planner system prompt\n\n```text\n'+prompts.agent_planner_system()+'\n```',
        '## VAM planner user template\n\n```text\n'+user+'\n```',
        'VAM indexing also uses event-caption/summary prompts; inspections use query text plus image_url '
        'and, where selected by upstream code, video_url parts. The shared question enters the retrieval '
        'goal after indexing, not as an answer-supervised indexing instruction.',
    ]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text('\n\n'.join(sections)+'\n')
    assert item['question'] in user and item['question'] in args.output.read_text()
    print(args.output)


if __name__ == '__main__':
    main()
