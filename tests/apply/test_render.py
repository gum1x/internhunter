from internhunter.apply.render import render_resume_pdf


def test_render_writes_pdf(tmp_path):
    out = render_resume_pdf("EXPERIENCE\n- Built a Flask API", tmp_path / "r.pdf")
    assert out.exists()
    assert out.read_bytes().startswith(b"%PDF")
