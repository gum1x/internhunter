from __future__ import annotations

from collections import defaultdict

from internhunter.core.dedup import _canonical_sort_key
from internhunter.core.models import NormalizedJob
from internhunter.match.embed import EmbeddingCache, Encoder, cosine_matrix, embed_texts


def _job_text(job: NormalizedJob) -> str:
    return f"{job.title}. {job.description_text}"


def _find(parent: list[int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def _union(parent: list[int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[max(ra, rb)] = min(ra, rb)


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
        # Connected components over the >=threshold similarity graph via union-find:
        # order-independent (unlike the old greedy single-link, which placed each job
        # into the first cluster it matched in input order). Only direct >=threshold
        # edges create unions.
        parent = list(range(len(indices)))
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                if sims[i, j] >= threshold:
                    _union(parent, i, j)

        components: dict[int, list[int]] = defaultdict(list)
        for local in range(len(indices)):
            components[_find(parent, local)].append(local)
        for members in components.values():
            groups.append([jobs[indices[local]] for local in members])

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
