from __future__ import annotations

from pathlib import Path


def render_resume_pdf(text: str, out_path: Path) -> Path:
    from fpdf import FPDF

    pdf = FPDF(format="letter")
    pdf.set_margins(left=0.5, top=0.5, right=0.5)
    pdf.set_auto_page_break(auto=True, margin=0.5)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    for line in text.splitlines() or [""]:
        # latin-1 is fpdf2's core-font encoding; drop unencodable glyphs rather than crash
        safe = line.encode("latin-1", "ignore").decode("latin-1")
        pdf.multi_cell(w=pdf.epw, h=6, text=safe)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(out_path))
    return out_path
