"""Sequence editing primitives with feature-coordinate remapping.

Every operation returns a new ``(sequence, features)`` pair plus a human readable
description, so the API layer can persist an immutable revision and an audit
trail instead of mutating state in place.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace as dataclass_replace

from .alphabet import clean_sequence, reverse_complement
from .seqio import Feature

Segments = list[tuple[int, int]]


def _rebuild(feature: Feature, segments: Segments, *, strand: int | None = None) -> Feature | None:
    segments = [(s, e) for s, e in segments if e > s]
    if not segments:
        return None
    return Feature(
        type=feature.type,
        segments=sorted(segments),
        strand=strand if strand is not None else feature.strand,
        name=feature.name,
        qualifiers=dict(feature.qualifiers),
        color=feature.color,
    )


def insert_sequence(
    sequence: str,
    features: Sequence[Feature],
    position: int,
    payload: str,
    *,
    extend_overlapping: bool = True,
) -> tuple[str, list[Feature], str]:
    payload = clean_sequence(payload)
    position = max(0, min(position, len(sequence)))
    new_seq = sequence[:position] + payload + sequence[position:]
    shift = len(payload)
    out: list[Feature] = []
    for feat in features:
        segments: Segments = []
        for start, end in feat.segments:
            if end <= position:
                segments.append((start, end))
            elif start >= position:
                segments.append((start + shift, end + shift))
            else:  # insertion lands inside the feature
                segments.append((start, end + shift) if extend_overlapping else (start, position))
                if not extend_overlapping:
                    segments.append((position + shift, end + shift))
        rebuilt = _rebuild(feat, segments)
        if rebuilt:
            out.append(rebuilt)
    return new_seq, out, f"Inserted {len(payload)} bp at position {position + 1}"


def delete_range(
    sequence: str,
    features: Sequence[Feature],
    start: int,
    end: int,
) -> tuple[str, list[Feature], str]:
    start, end = sorted((max(0, start), min(len(sequence), end)))
    if end <= start:
        return sequence, list(features), "No-op deletion"
    removed = end - start
    new_seq = sequence[:start] + sequence[end:]
    out: list[Feature] = []
    for feat in features:
        segments: Segments = []
        for f_start, f_end in feat.segments:
            if f_end <= start:
                segments.append((f_start, f_end))
            elif f_start >= end:
                segments.append((f_start - removed, f_end - removed))
            else:
                left = (f_start, min(f_end, start))
                right = (max(f_start, end) - removed, f_end - removed)
                if left[1] > left[0]:
                    segments.append(left)
                if right[1] > right[0]:
                    segments.append(right)
        rebuilt = _rebuild(feat, segments)
        if rebuilt:
            out.append(rebuilt)
    return new_seq, out, f"Deleted {removed} bp ({start + 1}..{end})"


def replace_range(
    sequence: str,
    features: Sequence[Feature],
    start: int,
    end: int,
    payload: str,
) -> tuple[str, list[Feature], str]:
    seq_after_delete, feats, _ = delete_range(sequence, features, start, end)
    new_seq, new_feats, _ = insert_sequence(seq_after_delete, feats, min(start, len(seq_after_delete)), payload)
    return new_seq, new_feats, f"Replaced {max(0, end - start)} bp at {start + 1} with {len(clean_sequence(payload))} bp"


def reverse_complement_all(
    sequence: str,
    features: Sequence[Feature],
) -> tuple[str, list[Feature], str]:
    n = len(sequence)
    new_seq = reverse_complement(sequence)
    out: list[Feature] = []
    for feat in features:
        segments = [(n - e, n - s) for s, e in feat.segments]
        rebuilt = _rebuild(feat, segments, strand=-feat.strand if feat.strand else 0)
        if rebuilt:
            out.append(rebuilt)
    return new_seq, out, "Reverse-complemented the whole sequence"


def reverse_complement_range(
    sequence: str,
    features: Sequence[Feature],
    start: int,
    end: int,
) -> tuple[str, list[Feature], str]:
    start, end = sorted((max(0, start), min(len(sequence), end)))
    if end <= start:
        return sequence, list(features), "No-op reverse complement"
    segment = sequence[start:end]
    new_seq = sequence[:start] + reverse_complement(segment) + sequence[end:]
    out: list[Feature] = []
    for feat in features:
        segments: Segments = []
        flip = False
        for f_start, f_end in feat.segments:
            if f_end <= start or f_start >= end:
                segments.append((f_start, f_end))
            elif f_start >= start and f_end <= end:
                segments.append((start + (end - f_end), start + (end - f_start)))
                flip = True
            else:  # straddles the boundary: keep the coordinates, flag the feature
                segments.append((f_start, f_end))
        rebuilt = _rebuild(feat, segments, strand=(-feat.strand if flip and feat.strand else feat.strand))
        if rebuilt:
            out.append(rebuilt)
    return new_seq, out, f"Reverse-complemented {start + 1}..{end}"


def set_origin(
    sequence: str,
    features: Sequence[Feature],
    new_origin: int,
) -> tuple[str, list[Feature], str]:
    """Rotate a circular sequence so ``new_origin`` becomes position 1."""
    n = len(sequence)
    if n == 0:
        return sequence, list(features), "No-op rotation"
    shift = new_origin % n
    new_seq = sequence[shift:] + sequence[:shift]
    out: list[Feature] = []
    for feat in features:
        segments: Segments = []
        for start, end in feat.segments:
            new_start = (start - shift) % n
            length = end - start
            if new_start + length <= n:
                segments.append((new_start, new_start + length))
            else:  # feature now spans the origin: split into two segments
                segments.append((new_start, n))
                segments.append((0, (new_start + length) % n))
        rebuilt = _rebuild(feat, segments)
        if rebuilt:
            out.append(rebuilt)
    return new_seq, out, f"Set origin to position {shift + 1}"


def add_feature(
    features: Sequence[Feature],
    *,
    start: int,
    end: int,
    name: str,
    feature_type: str = "misc_feature",
    strand: int = 1,
    color: str | None = None,
    qualifiers: dict | None = None,
) -> tuple[list[Feature], str]:
    feat = Feature(
        type=feature_type,
        segments=[(min(start, end), max(start, end))],
        strand=strand,
        name=name,
        qualifiers=qualifiers or {"label": name},
        color=color,
    )
    return list(features) + [feat], f"Added feature {name} ({start + 1}..{end})"


def remove_feature(features: Sequence[Feature], index: int) -> tuple[list[Feature], str]:
    out = list(features)
    if 0 <= index < len(out):
        removed = out.pop(index)
        return out, f"Removed feature {removed.name}"
    return out, "Feature index out of range"


def update_feature(
    features: Sequence[Feature],
    index: int,
    **changes,
) -> tuple[list[Feature], str]:
    out = list(features)
    if not (0 <= index < len(out)):
        return out, "Feature index out of range"
    feat = out[index]
    segments = changes.pop("segments", None)
    if segments:
        changes["segments"] = [tuple(s) for s in segments]
    out[index] = dataclass_replace(feat, **changes)
    return out, f"Updated feature {out[index].name}"


OPERATIONS = {
    "insert": insert_sequence,
    "delete": delete_range,
    "replace": replace_range,
    "reverse_complement": reverse_complement_all,
    "reverse_complement_range": reverse_complement_range,
    "set_origin": set_origin,
}
