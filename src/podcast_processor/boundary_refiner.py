import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import litellm
from jinja2 import Template

from shared.config import Config


@dataclass
class BoundaryRefinement:
    refined_start: float
    refined_end: float
    start_reason: str
    end_reason: str


class BoundaryRefiner:
    def __init__(self, config: Config, logger: Optional[logging.Logger] = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        self.template = self._load_template()

    def _load_template(self) -> Template:
        path = (
            Path(__file__).resolve().parent.parent  # project src root
            / "boundary_refinement_prompt.jinja"
        )
        if path.exists():
            return Template(path.read_text())
        # Minimal fallback
        return Template(
            """Refine ad boundaries.
Ad: {{ad_start}}s-{{ad_end}}s
{% for seg in context_segments %}[{{seg.start_time}}] {{seg.text}}
{% endfor %}
Return JSON: {"refined_start": {{ad_start}}, "refined_end": {{ad_end}}, "start_reason": "", "end_reason": ""}"""
        )

    def refine(
        self,
        ad_start: float,
        ad_end: float,
        confidence: float,
        all_segments: List[Dict[str, Any]],
    ) -> BoundaryRefinement:
        """Refine ad boundaries using LLM analysis"""
        context = self._get_context(ad_start, ad_end, all_segments)

        try:
            # Try LLM refinement
            prompt = self.template.render(
                ad_start=ad_start,
                ad_end=ad_end,
                ad_confidence=confidence,
                context_segments=context,
                max_start_extension=getattr(
                    self.config, "max_start_extension_seconds", 30.0
                ),
                max_end_extension=getattr(
                    self.config, "max_end_extension_seconds", 15.0
                ),
            )

            response = litellm.completion(
                model=self.config.llm_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=500,
                timeout=self.config.openai_timeout,
            )

            content = response.choices[0].message.content
            # Parse JSON (strip markdown fences)
            cleaned = re.sub(r"```json|```", "", content.strip())
            match = re.search(r"\{[^}]+\}", cleaned)
            if match:
                data = json.loads(match.group(0))
                return self._validate(
                    ad_start,
                    ad_end,
                    BoundaryRefinement(
                        refined_start=float(data["refined_start"]),
                        refined_end=float(data["refined_end"]),
                        start_reason=data.get("start_reason", ""),
                        end_reason=data.get("end_reason", ""),
                    ),
                )
        except Exception as e:
            self.logger.warning(f"LLM refinement failed: {e}, using heuristic")

        # Fallback: heuristic refinement
        return self._heuristic_refine(ad_start, ad_end, context)

    def _get_context(
        self, ad_start: float, ad_end: float, all_segments: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Get ±8 segments around ad"""
        ad_segs = [s for s in all_segments if ad_start <= s["start_time"] <= ad_end]
        if not ad_segs:
            return []

        first_idx = all_segments.index(ad_segs[0])
        last_idx = all_segments.index(ad_segs[-1])

        start_idx = max(0, first_idx - 8)
        end_idx = min(len(all_segments), last_idx + 9)

        return all_segments[start_idx:end_idx]

    def _heuristic_refine(
        self, ad_start: float, ad_end: float, context: List[Dict[str, Any]]
    ) -> BoundaryRefinement:
        """Simple pattern-based refinement"""
        intro_patterns = ["brought to you", "sponsor", "let me tell you"]
        outro_patterns = [".com", "thanks to", "use code", "visit"]

        refined_start = ad_start
        refined_end = ad_end

        # Check before ad for intros
        for seg in context:
            if seg["start_time"] < ad_start:
                if any(p in seg["text"].lower() for p in intro_patterns):
                    refined_start = seg["start_time"]

        # Check after ad for outros
        for seg in context:
            if seg["start_time"] > ad_end:
                if any(p in seg["text"].lower() for p in outro_patterns):
                    refined_end = seg.get("end_time", seg["start_time"] + 5.0)

        return BoundaryRefinement(refined_start, refined_end, "heuristic", "heuristic")

    def _validate(
        self, orig_start: float, orig_end: float, refinement: BoundaryRefinement
    ) -> BoundaryRefinement:
        """Constrain refinement to reasonable bounds"""
        max_start_ext = getattr(self.config, "max_start_extension_seconds", 30.0)
        max_end_ext = getattr(self.config, "max_end_extension_seconds", 15.0)

        refinement.refined_start = max(
            refinement.refined_start, orig_start - max_start_ext
        )
        refinement.refined_end = min(refinement.refined_end, orig_end + max_end_ext)
        if refinement.refined_start >= refinement.refined_end:
            refinement.refined_start = orig_start
            refinement.refined_end = orig_end

        return refinement
