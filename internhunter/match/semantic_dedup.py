from __future__ import annotations

from collections import defaultdict

from internhunter.core.dedup import _canonical_sort_key
from internhunter.core.models import NormalizedJob
from internhunter.match.embed import EmbeddingCache, Encoder, cosine_matrix, embed_texts


def _job_text(job: NormalizedJob) -> str:
    return f"{job.title}. {job.description_text}"


def semantic_groups(
    jobs: list[NormalizedJob],
    encoder: Encoder,
    threshold: float = 0.9,
    cache: EmbeddingCache | None = None,
) -> list[list[NormalizedJob]]:
    if not jobs:
        return []

    vectors = embed_texts([_job_text(job) for job in jobs], encoder, cache)

    by_company: dict[str, list[int]] = defaultdict(list)
    for index, job in enumerate(jobs):
        by_company[job.company_slug].append(index)

    groups: list[list[NormalizedJob]] = []
    for indices in by_company.values():
        block = vectors[indices]
        sims = cosine_matrix(block, block)
        clusters: list[list[tuple[int, int]]] = []
        for local, index in enumerate(indices):
            placed = False
            for cluster in clusters:
                if any(sims[local, member] >= threshold for member, _ in cluster):
                    cluster.append((local, index))
                    placed = True
                    break
            if not placed:
                clusters.append([(local, index)])
        for cluster in clusters:
            groups.append([jobs[index] for _, index in cluster])

    return groups


def collapse_semantic(
    jobs: list[NormalizedJob],
    encoder: Encoder,
    threshold: float = 0.9,
    cache: EmbeddingCache | None = None,
) -> tuple[list[NormalizedJob], int]:
    canonicals: list[NormalizedJob] = []
    merged = 0
    for group in semantic_groups(jobs, encoder, threshold, cache):
        canonical = min(group, key=_canonical_sort_key)
        canonical.times_seen_elsewhere += len(group) - 1
        merged += len(group) - 1
        canonicals.append(canonical)
    return (canonicals, merged)
