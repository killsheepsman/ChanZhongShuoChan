from __future__ import annotations

from .models import Center, Segment


def detect_centers(segments: list[Segment]) -> list[Center]:
    centers: list[Center] = []
    if len(segments) < 3:
        return centers

    i = 0
    while i <= len(segments) - 3:
        group = segments[i : i + 3]
        zg = min(segment.high for segment in group)
        zd = max(segment.low for segment in group)
        if zg <= zd:
            i += 1
            continue

        extended = list(group)
        j = i + 3
        while j < len(segments):
            candidate = segments[j]
            if not (candidate.high > zd and candidate.low < zg):
                break
            extended.append(candidate)
            j += 1

        centers.append(
            Center(
                id=len(centers),
                start_index=extended[0].start_index,
                end_index=extended[-1].end_index,
                start_time=extended[0].start_time,
                end_time=extended[-1].end_time,
                zg=zg,
                zd=zd,
                gg=max(segment.high for segment in extended),
                dd=min(segment.low for segment in extended),
                segment_ids=[segment.id for segment in extended],
            )
        )
        i = max(j, i + 1)
    return centers
