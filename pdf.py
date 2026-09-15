"""Output rendering (stage 13). Per record: address heading, a details table of the
computed figures, then the narrative, a deterministic next-course-of-action recommendation,
and finally the on-site verification links -- in that order, so a reader gets the numbers
before the prose, and the recommended next step before being sent off to check a map."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PDF_DISCLAIMER = "Estimate — not a guaranteed return figure"

AREA_LEVEL_MATCH_TYPES = {"road", "suburb", "postcode", "city", None}


def _details_rows(record: dict) -> list[tuple[str, str]]:
    rows = [("Path", record["pipeline_path"])]
    if record.get("tier"):
        rows.append(("Tier", record["tier"]))
    if record.get("optimal_tilt_degrees") is not None:
        rows.append((
            "Recommended tilt / azimuth",
            f"{record['optimal_tilt_degrees']}° / {record['optimal_azimuth_degrees']}°",
        ))
    if record.get("regional_irradiance") is not None:
        rows.append(("Regional irradiance", f"{record['regional_irradiance']} kWh/m²/day"))
    if record.get("estimated_shaded_hours") is not None:
        rows.append(("Estimated shaded hours/yr", f"{record['estimated_shaded_hours']:.0f}"))
    rows.append(("Confidence", "Verified" if record.get("confidence") == "verified" else "Estimated"))
    return rows


def _next_course_of_action(record: dict) -> str:
    """Deterministic, rule-based -- like scoring itself -- rather than left to the LLM
    narrative, so the recommended action always matches the tier/flags that produced it."""
    if record["pipeline_path"] == "NEW_BUILD":
        action = (
            "Use the recommended tilt and azimuth as a design starting point, and schedule a "
            "site visit to confirm that orientation is actually buildable."
        )
    else:
        tier = record.get("tier")
        if tier == "HIGH":
            action = "Strong candidate — prioritize for a full site inspection and formal quote."
        elif tier == "MEDIUM":
            action = "Worth pursuing — schedule a site visit to confirm the estimate before quoting."
        elif tier == "LOW":
            action = (
                "Deprioritize unless a site visit finds materially better shading or roof "
                "conditions than estimated here."
            )
        else:
            action = "Insufficient data to recommend a next step — verify this address manually."

    checks = []
    if record.get("ambiguous_existence"):
        checks.append("confirm whether a structure currently exists on site")
    if record.get("verify_adjacent_structure"):
        checks.append("confirm whether a nearby structure actually shades this roof")
    if record.get("low_confidence_geocode"):
        checks.append("confirm the pinned location is the correct address")
    if checks:
        action += " Before contacting this lead, " + "; ".join(checks) + "."
    return action


def build_results_pdf(records: list[dict]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], textColor=colors.red, fontSize=12, spaceAfter=16
    )
    section_heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading3"], spaceBefore=10, spaceAfter=4
    )
    link_style = ParagraphStyle("Link", parent=styles["Normal"], textColor=colors.blue, underlineWidth=1)
    geocode_warning_style = ParagraphStyle(
        "GeocodeWarning", parent=styles["Normal"], textColor=colors.HexColor("#92660a"), spaceBefore=6, spaceAfter=4
    )
    unavailable_style = ParagraphStyle(
        "Unavailable", parent=styles["Normal"], textColor=colors.HexColor("#5b6866"), fontName="Helvetica-Oblique"
    )
    detail_label_style = ParagraphStyle("DetailLabel", parent=styles["Normal"], fontName="Helvetica-Bold")
    detail_value_style = ParagraphStyle("DetailValue", parent=styles["Normal"])

    story = [
        Paragraph("Solar Lead Pre-Qualifier — Results", styles["Title"]),
        Paragraph(PDF_DISCLAIMER, disclaimer_style),
    ]

    for i, record in enumerate(records):
        if i > 0:
            story.append(HRFlowable(width="100%", color=colors.HexColor("#dfe4e2"), spaceBefore=6, spaceAfter=14))

        story.append(Paragraph(record["address"], styles["Heading2"]))

        detail_data = [
            [Paragraph(label, detail_label_style), Paragraph(str(value), detail_value_style)]
            for label, value in _details_rows(record)
        ]
        detail_table = Table(detail_data, colWidths=[170, 330], hAlign="LEFT")
        detail_table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dfe4e2")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#fafbfa")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(detail_table)

        if record.get("low_confidence_geocode"):
            if record.get("geocode_type") in AREA_LEVEL_MATCH_TYPES:
                warning_text = (
                    "<b>Warning:</b> approximate location only — the pin may show the wrong building. "
                    "Verify the address manually before relying on this result."
                )
            else:
                warning_text = "<b>Warning:</b> location approximate — please verify."
            story.append(Paragraph(warning_text, geocode_warning_style))

        story.append(Paragraph("Assessment", section_heading_style))
        if record.get("narrative"):
            story.append(Paragraph(record["narrative"], styles["Normal"]))
        else:
            reason = record.get("narrative_unavailable_reason") or "Narrative unavailable."
            story.append(Paragraph(f"Narrative unavailable: {reason}", unavailable_style))

        story.append(Paragraph("Next course of action", section_heading_style))
        story.append(Paragraph(_next_course_of_action(record), styles["Normal"]))

        if record.get("google_maps_link") or record.get("street_view_link"):
            story.append(Paragraph("Verify on-site", section_heading_style))
            if record.get("google_maps_link"):
                story.append(Paragraph(
                    f'<link href="{record["google_maps_link"]}"><u>Open in Google Maps</u></link>', link_style
                ))
            if record.get("street_view_link"):
                story.append(Paragraph(
                    f'<link href="{record["street_view_link"]}"><u>Open in Street View</u></link>', link_style
                ))

        story.append(Spacer(1, 4))

    doc.build(story)
    return buffer.getvalue()
