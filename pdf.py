"""Output rendering (stage 13). One flowable block per record (not a table) so narrative
paragraphs can wrap naturally, headed clearly so no reader mistakes this for a guaranteed figure."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

PDF_DISCLAIMER = "Estimate — not a guaranteed return figure"


def build_results_pdf(records: list[dict]) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], textColor=colors.red, fontSize=12, spaceAfter=16
    )
    link_style = ParagraphStyle("Link", parent=styles["Normal"], textColor=colors.blue, underlineWidth=1)
    geocode_warning_style = ParagraphStyle(
        "GeocodeWarning", parent=styles["Normal"], textColor=colors.HexColor("#92660a"), spaceAfter=4
    )

    AREA_LEVEL_MATCH_TYPES = {"road", "suburb", "postcode", "city", None}

    story = [
        Paragraph("Solar Lead Pre-Qualifier — Results", styles["Title"]),
        Paragraph(PDF_DISCLAIMER, disclaimer_style),
    ]

    for record in records:
        story.append(Paragraph(record["address"], styles["Heading2"]))

        result_line = f"Path: {record['pipeline_path']}"
        if record.get("tier"):
            result_line += f" | Tier: {record['tier']}"
        if record.get("optimal_tilt_degrees") is not None:
            result_line += (
                f" | Recommended tilt: {record['optimal_tilt_degrees']}° / "
                f"azimuth: {record['optimal_azimuth_degrees']}°"
            )
        if record.get("regional_irradiance") is not None:
            result_line += f" | Regional irradiance: {record['regional_irradiance']} kWh/m2/day"
        if record.get("estimated_shaded_hours") is not None:
            result_line += f" | Estimated shaded hours/yr: {record['estimated_shaded_hours']:.0f}"
        story.append(Paragraph(result_line, styles["Normal"]))

        if record.get("narrative"):
            story.append(Paragraph(record["narrative"], styles["Normal"]))
        if record.get("low_confidence_geocode"):
            if record.get("geocode_type") in AREA_LEVEL_MATCH_TYPES:
                warning_text = (
                    "<b>Warning:</b> approximate location only — the pin may show the wrong building. "
                    "Verify the address manually before relying on this result."
                )
            else:
                warning_text = "<b>Warning:</b> location approximate — please verify."
            story.append(Paragraph(warning_text, geocode_warning_style))
        if record.get("google_maps_link"):
            story.append(Paragraph(
                f'<link href="{record["google_maps_link"]}"><u>Verify on Google Maps</u></link>', link_style
            ))
        if record.get("street_view_link"):
            story.append(Paragraph(
                f'<link href="{record["street_view_link"]}"><u>Verify on Street View</u></link>', link_style
            ))

        story.append(Spacer(1, 16))

    doc.build(story)
    return buffer.getvalue()
