from __future__ import annotations

from .models import Center, CenterDirection, CenterExpansion, Segment


def detect_centers(segments: list[Segment]) -> list[Center]:
    """Identify fixed-core centers from confirmed, same-level segments."""
    centers: list[Center] = []
    index = 0
    while index <= len(segments) - 3:
        seed = segments[index : index + 3]
        overlap = _overlap(seed)
        if overlap is None:
            index += 1
            continue

        zd, zg = overlap
        members = list(seed)
        cursor = index + 3
        while cursor < len(segments) and _intersects_core(segments[cursor], zd, zg):
            members.append(segments[cursor])
            cursor += 1

        previous = centers[-1] if centers else None
        centers.append(
            Center(
                id=len(centers),
                start_index=members[0].start_index,
                end_index=members[-1].end_index,
                start_time=members[0].start_time,
                end_time=members[-1].end_time,
                zg=zg,
                zd=zd,
                gg=max(segment.high for segment in members),
                dd=min(segment.low for segment in members),
                segment_ids=[segment.id for segment in members],
                direction=_direction(previous, zd, zg),
                extend_count=len(members) - 3,
                status="ENDED" if cursor < len(segments) else "RUNNING",
                break_segment_id=segments[cursor].id if cursor < len(segments) else None,
            )
        )
        # The first non-overlapping segment is the first possible segment of
        # the next center and must not be skipped.
        index = cursor
    return centers


def detect_center_expansions(centers: list[Center]) -> list[CenterExpansion]:
    """Return pairwise higher-level candidates without transitive merging."""
    expansions: list[CenterExpansion] = []
    for left, right in zip(centers, centers[1:]):
        overlap_low = max(left.dd, right.dd)
        overlap_high = min(left.gg, right.gg)
        if overlap_high <= overlap_low:
            continue
        expansions.append(
            CenterExpansion(
                id=f"E{len(expansions) + 1}",
                center_ids=[left.id, right.id],
                overlap_low=overlap_low,
                overlap_high=overlap_high,
                gg=max(left.gg, right.gg),
                dd=min(left.dd, right.dd),
            )
        )
    return expansions


def _overlap(segments: list[Segment]) -> tuple[float, float] | None:
    if len(segments) != 3:
        return None
    zg = min(segment.high for segment in segments)
    zd = max(segment.low for segment in segments)
    return (zd, zg) if zg > zd else None


def _intersects_core(segment: Segment, zd: float, zg: float) -> bool:
    return segment.high > zd and segment.low < zg


def _direction(previous: Center | None, zd: float, zg: float) -> CenterDirection:
    if previous is None:
        return "NONE"
    if zd > previous.zg:
        return "UP"
    if zg < previous.zd:
        return "DOWN"
    return "SIDEWAYS"
