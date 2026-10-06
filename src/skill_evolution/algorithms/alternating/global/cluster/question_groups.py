"""Train-input Louvain index and bounded, versioned trajectory references."""
import json
import math
from pathlib import Path

import networkx as nx
import numpy as np
from models.embeddings import embed
from skill_evolution.infra.skills import hash_json
from skill_evolution.infra.store import write_json

INSTRUCTION = 'Retrieve multi-video questions requiring the same reasoning and evidence acquisition strategy, regardless of subject matter, benchmark or wording.'


def question_text(value):
    question = value['question']
    if not isinstance(question, str) or not question.strip():
        raise ValueError('Question input must be nonempty')
    options = value.get('options', [])
    if options and '\nOptions:\n' not in question:
        question += '\n\nOptions:\n' + '\n'.join(options)
    videos = []
    for video in value['videos']:
        duration = video['duration_sec']
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            raise ValueError('Question clustering requires finite positive video duration')
        videos.append(f"{video['video_id']}: duration={duration} seconds")
    if not videos:
        raise ValueError('Question clustering requires video metadata')
    return f'Instruct: {INSTRUCTION}\nQuery: {question}\n\nVideos:\n' + '\n'.join(videos)


class QuestionGroups:
    def __init__(self, config, root):
        self.config, self.root = config, Path(root)

    def build(self, inputs):
        self.ids = sorted(inputs)
        texts = tuple(question_text(inputs[sid]) for sid in self.ids)
        identity = hash_json([self.config.to_dict(), self.ids, texts])
        rows = []
        for start in range(0, len(texts), 32):
            batch = texts[start:start + 32]
            path = self.root / (hash_json([self.config.to_dict(), batch]) + '.json')
            if path.exists():
                vectors = np.asarray(json.loads(path.read_text()), dtype=float)
            else:
                vectors = embed(self.config, batch)
                write_json(path, vectors.tolist())
            if (vectors.ndim != 2 or vectors.shape[0] != len(batch)
                    or not np.isfinite(vectors).all()
                    or not np.allclose(np.linalg.norm(vectors, axis=1), 1)):
                raise ValueError('Invalid cached question vectors')
            rows.extend(vectors)
        self.vectors = np.asarray(rows)
        graph = nx.Graph()
        graph.add_nodes_from(range(len(self.ids)))
        neighbors = []
        # Bound similarity working memory; full Train embeddings stay resident.
        for start in range(0, len(self.ids), 128):
            similarity = self.vectors[start:start + 128] @ self.vectors.T
            for offset, row in enumerate(similarity):
                index = start + offset
                row[index] = -np.inf
                order = np.argsort(-row, kind='stable')[:min(32, len(self.ids) - 1)]
                neighbors.append({int(j): float(row[j]) for j in order if row[j] >= .55})
        for i, near in enumerate(neighbors):
            for j, weight in near.items():
                if i < j and i in neighbors[j]:
                    graph.add_edge(i, j, weight=weight)
        communities = (nx.community.louvain_communities(graph, resolution=2, seed=20261001)
                       if graph.number_of_edges() else [{i} for i in graph])
        groups = sorted([sorted(self.ids[i] for i in group) for group in communities])
        self.labels = {sid: group[0] for group in groups for sid in group}
        self.positions = {sid: i for i, sid in enumerate(self.ids)}
        return dict(identity=identity, algorithm='mutual-knn-louvain', k=32, threshold=.55,
            resolution=2, seed=20261001, groups=groups,
            unclassified=[self.ids[i] for i in graph if graph.degree(i) == 0])

