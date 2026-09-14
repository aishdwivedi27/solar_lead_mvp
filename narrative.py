"""LLM narrative (stage 12). The model is fed only the already-computed ScoreResult and
confidence flags -- never a coordinate, address, or API of its own -- and is instructed to
phrase those values, not add to them. This keeps the score the actual decision-maker; the
narrative is presentation only."""

from llm.base import NarrativeProvider
from scoring import ScoreResult

NARRATIVE_SYSTEM_PROMPT = """You write a short pros/cons paragraph for one address in a solar \
lead-qualification report, for a salesperson to read before contacting the lead.

You will be given a fixed set of already-computed values: either a HIGH/MEDIUM/LOW suitability \
tier, or (for a new-build site) a recommended panel tilt/azimuth instead of a tier; regional solar \
irradiance; an estimated annual shaded-hours figure; and boolean confidence flags.

Rules, followed strictly:
- Use only the values given below. Do not invent, estimate, or restate any figure, percentage, or \
claim that is not explicitly present in the input.
- If a value is absent from the input, do not mention it or guess a substitute -- simply omit it.
- Mention every flag that is true as something for the salesperson to double-check on site or via \
the verification links already included elsewhere in the report -- do not describe or guess what \
those links would show.
- Never state or imply a financial return, savings figure, or guaranteed outcome.
- Write 2-4 plain sentences, one paragraph, no markdown, no headings, no bullet list."""


def _narrative_input_summary(record: dict, score_result: ScoreResult) -> str:
    lines = [f"pipeline_path: {score_result.pipeline_path}"]
    if score_result.tier is not None:
        lines.append(f"tier: {score_result.tier}")
    if score_result.optimal_tilt_degrees is not None:
        lines.append(f"recommended_optimal_tilt_degrees: {score_result.optimal_tilt_degrees}")
    if score_result.optimal_azimuth_degrees is not None:
        lines.append(f"recommended_optimal_azimuth_degrees: {score_result.optimal_azimuth_degrees}")
    if score_result.regional_irradiance is not None:
        lines.append(f"regional_irradiance_kwh_per_m2_per_day: {score_result.regional_irradiance}")
    if score_result.estimated_shaded_hours is not None:
        lines.append(f"estimated_shaded_hours_per_year: {score_result.estimated_shaded_hours}")
    lines.append(f"ambiguous_existence: {record.get('ambiguous_existence')}")
    lines.append(f"low_confidence_geocode: {record.get('low_confidence_geocode')}")
    lines.append(f"verify_adjacent_structure: {record.get('verify_adjacent_structure')}")
    return "\n".join(lines)


def generate_narrative(
    provider: NarrativeProvider | None, record: dict, score_result: ScoreResult
) -> str | None:
    if provider is None:
        return None
    return provider.generate(NARRATIVE_SYSTEM_PROMPT, _narrative_input_summary(record, score_result))
