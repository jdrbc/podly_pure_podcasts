import re
from dataclasses import dataclass
from typing import Dict, List, Pattern

from app.models import Identification, TranscriptSegment


@dataclass
class AdGroup:
    segments: List[TranscriptSegment]
    identifications: List[Identification]
    start_time: float
    end_time: float
    confidence_avg: float
    keywords: List[str]


class AdMerger:
    def __init__(self) -> None:
        self.url_pattern: Pattern[str] = re.compile(
            r"\b([a-z0-9\-\.]+\.(?:com|net|org|io))\b", re.I
        )
        self.promo_pattern: Pattern[str] = re.compile(
            r"\b(code|promo|save)\s+\w+\b", re.I
        )
        self.phone_pattern: Pattern[str] = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{4}\b")

    def merge(
        self,
        ad_segments: List[TranscriptSegment],
        identifications: List[Identification],
        max_gap: float = 8.0,
        min_content_gap: float = 12.0,
    ) -> List[AdGroup]:
        """Merge ad segments using content analysis"""
        if not ad_segments:
            return []

        # Sort by time
        ad_segments = sorted(ad_segments, key=lambda s: s.start_time)

        # Group by proximity
        groups = self._group_by_proximity(ad_segments, identifications, max_gap)

        # Refine using content analysis
        groups = self._refine_by_content(groups, min_content_gap)

        # Filter weak groups
        return [g for g in groups if self._is_valid_group(g)]

    def _group_by_proximity(
        self,
        segments: List[TranscriptSegment],
        identifications: List[Identification],
        max_gap: float,
    ) -> List[AdGroup]:
        """Initial grouping by time proximity"""
        id_lookup: Dict[int, Identification] = {
            i.transcript_segment_id: i for i in identifications
        }
        groups: List[AdGroup] = []
        current: List[TranscriptSegment] = []

        for seg in segments:
            if not current or seg.start_time - current[-1].end_time <= max_gap:
                current.append(seg)
            else:
                if current:
                    groups.append(self._create_group(current, id_lookup))
                current = [seg]

        if current:
            groups.append(self._create_group(current, id_lookup))

        return groups

    def _create_group(
        self,
        segments: List[TranscriptSegment],
        id_lookup: Dict[int, Identification],
    ) -> AdGroup:
        ids = [id_lookup[s.id] for s in segments if s.id in id_lookup]
        return AdGroup(
            segments=segments,
            identifications=ids,
            start_time=segments[0].start_time,
            end_time=segments[-1].end_time,
            confidence_avg=sum(i.confidence for i in ids) / len(ids) if ids else 0.0,
            keywords=self._extract_keywords(segments),
        )

    def _extract_keywords(self, segments: List[TranscriptSegment]) -> List[str]:
        """Extract URLs, promo codes, brands"""
        text = " ".join(s.text or "" for s in segments).lower()
        keywords: List[str] = []

        # URLs
        keywords.extend(self.url_pattern.findall(text))

        # Promo codes
        keywords.extend(self.promo_pattern.findall(text))

        # Phone numbers
        if self.phone_pattern.search(text):
            keywords.append("phone")

        # Brand names (capitalized words appearing 2+ times)
        words = re.findall(r"\b[A-Z][a-z]+\b", " ".join(s.text for s in segments))
        counts: Dict[str, int] = {}
        for word in words:
            if len(word) > 3:
                counts[word] = counts.get(word, 0) + 1
        keywords.extend(w.lower() for w, c in counts.items() if c >= 2)

        return list(set(keywords))

    def _refine_by_content(
        self, groups: List[AdGroup], min_content_gap: float
    ) -> List[AdGroup]:
        """Merge groups with shared sponsors"""
        if len(groups) <= 1:
            return groups

        refined: List[AdGroup] = []
        i = 0

        while i < len(groups):
            current = groups[i]

            if i + 1 < len(groups):
                next_group = groups[i + 1]
                gap = next_group.start_time - current.end_time

                if gap <= min_content_gap and self._should_merge(current, next_group):
                    # Merge
                    merged = AdGroup(
                        segments=current.segments + next_group.segments,
                        identifications=current.identifications
                        + next_group.identifications,
                        start_time=current.start_time,
                        end_time=next_group.end_time,
                        confidence_avg=(
                            current.confidence_avg + next_group.confidence_avg
                        )
                        / 2,
                        keywords=list(set(current.keywords + next_group.keywords)),
                    )
                    refined.append(merged)
                    i += 2
                else:
                    refined.append(current)
                    i += 1
            else:
                refined.append(current)
                i += 1

        return refined

    def _should_merge(self, group1: AdGroup, group2: AdGroup) -> bool:
        """Check if groups belong to same sponsor"""
        # High confidence → merge
        if group1.confidence_avg >= 0.9 and group2.confidence_avg >= 0.9:
            return True

        # Shared keywords (URL or brand)
        shared = set(group1.keywords) & set(group2.keywords)
        if len(shared) >= 1:
            return True

        # Small gap with good confidence
        gap = group2.start_time - group1.end_time
        if (
            gap <= 10.0
            and group1.confidence_avg >= 0.8
            and group2.confidence_avg >= 0.8
        ):
            return True

        return False

    def _is_valid_group(self, group: AdGroup) -> bool:
        """Filter out weak single-segment groups"""
        duration = group.end_time - group.start_time
        if len(group.segments) < 2 or duration <= 10.0:
            # Keep only if has strong keywords or high confidence
            return len(group.keywords) >= 1 or group.confidence_avg >= 0.9
        return True
