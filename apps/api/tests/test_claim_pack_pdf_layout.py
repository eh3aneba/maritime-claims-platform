"""Synthetic page geometry; no H&M semantic acceptance or source modification."""
from copy import deepcopy
from io import BytesIO

import pytest
from pypdf import PdfReader
from pypdf.generic._font import Font

from app.modules.claim_packs import renderers as base
from app.modules.claim_packs.recovery_renderers import render_pdf
from tests.test_claim_pack_recovery_reporting import _export_snapshot


SOURCE = 'W' * 75 + ' is not established.'


def assert_body_fits_and_collect(reader: PdfReader) -> str:
    pieces = []
    for page in reader.pages:
        def visit(text, cm, tm, font_dict, font_size):
            if font_size != 9 or not text.strip():
                return
            # Inspect the emitted font/page, not the application's wrap helper.
            font = Font.from_font_resource(font_dict)
            for line in text.splitlines():
                width = font.get_text_width(line) * font_size / 1000
                assert tm[4] >= 54
                assert tm[4] + width <= float(page.mediabox.right) - 54 + 0.01
            pieces.append(text)
        page.extract_text(visitor_text=visit)
    return ''.join(pieces)


@pytest.mark.parametrize('section', ['main', 'governed_appendix'])
@pytest.mark.parametrize('source', [SOURCE, 'i' * 200 + ' is not established.', '€—' * 60 + ' is not established.'])
def test_wide_source_and_negation_stay_inside_page_without_snapshot_rewrite(section, source):
    snapshot = _export_snapshot()
    if section == 'main':
        snapshot['claim']['vessel_name'] = source
        renderer = base.render_pdf
    else:
        snapshot['recovery_review']['decisions'][0]['rationale'] = source
        renderer = render_pdf
    before = deepcopy(snapshot)
    body = assert_body_fits_and_collect(PdfReader(BytesIO(renderer(snapshot))))
    assert ''.join(source.split()) in ''.join(body.split())
    assert snapshot == before


def test_repeated_wide_multiline_appendix_survives_pagination():
    snapshot = _export_snapshot()
    source = '\r\n'.join([SOURCE + '\tSource reviewed only.'] * 90)
    snapshot['recovery_review']['decisions'][0]['rationale'] = source
    before = deepcopy(snapshot)
    reader = PdfReader(BytesIO(render_pdf(snapshot)))
    assert len(reader.pages) > 2
    body = assert_body_fits_and_collect(reader)
    assert ''.join(body.split()).count(''.join(SOURCE.split())) == 90
    assert snapshot == before


def test_unknown_font_metrics_fail_closed_without_leaking_source():
    from openpyxl import load_workbook
    snapshot = _export_snapshot()
    source = 'Synthetic\u00a0unmeasured source'
    snapshot['claim']['vessel_name'] = source
    with pytest.raises(base.UnsupportedClaimPackPDFTextError) as error:
        render_pdf(snapshot)
    assert source not in str(error.value)
    workbook = load_workbook(BytesIO(base.render_xlsx(snapshot)), read_only=True)
    try:
        assert source in [cell for row in workbook['Pack Summary'].values for cell in row]
    finally:
        workbook.close()


@pytest.mark.parametrize('source', [SOURCE, '  ' + SOURCE])
def test_direct_appendix_writer_also_bounds_wide_source(source):
    from app.modules.claim_packs.recovery_renderers import _text_pdf
    body = assert_body_fits_and_collect(PdfReader(BytesIO(_text_pdf([source]))))
    assert ''.join(SOURCE.split()) in ''.join(body.split())
