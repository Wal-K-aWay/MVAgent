"""A bounded text/vision replay for the new HTTP adapter path, without scoring."""
import argparse
import json
from pathlib import Path

from common import LocalQwen, write


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--endpoint',required=True)
    args=p.parse_args()
    rows=[json.loads(line) for line in args.source.read_text().splitlines()]
    selected={}
    for row in rows:
        visual=any(isinstance(m['content'],list) and any(part.get('type')=='image_url' for part in m['content'])
                   for m in row['request']['messages'])
        selected.setdefault('vision' if visual else 'text',row)
    assert set(selected)=={'text','vision'}
    client=LocalQwen(args.endpoint,args.output/'requests.jsonl')
    report=[]
    for role,row in selected.items():
        prior=row['response']
        result=client.chat(row['request']['messages'],row['request']['max_tokens'])
        left,right=prior['choices'][0]['token_ids'],result['choices'][0]['token_ids']
        same_input=prior['audit']['input_sha256']==result['audit']['input_sha256']
        same_prompt=prior['audit']['prompt_token_ids_sha256']==result['audit']['prompt_token_ids_sha256']
        different=next((i for i,(a,b) in enumerate(zip(left,right)) if a!=b),None)
        if different is None and len(left)!=len(right):
            different=min(len(left),len(right))
        report.append(dict(role=role,same_input=same_input,same_prompt=same_prompt,
            identical_tokens=left==right,first_different_token=different,
            original_worker=prior['audit']['worker'],repeat_worker=result['audit']['worker']))
    write(args.output/'comparison.json',report)
    print(json.dumps(report))
    assert all(r['same_input'] and r['same_prompt'] and r['identical_tokens'] for r in report)


if __name__=='__main__':
    main()
