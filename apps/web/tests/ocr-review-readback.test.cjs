// Synthetic audit DTOs only; no real reviewer assertion or application writes.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const Module = require('node:module');
const filename = path.resolve(__dirname, '../src/lib/ocr-review-readback.ts');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const loaded = new Module(filename, module);
loaded._compile(compiled, filename);
const { parseOcrReviewReadback, parseOcrWorkpaperReadback } = loaded.exports;
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const report = {
  id: id(1), document_id: id(2), reported_by_id: id(3),
  source_file_hash: 'a'.repeat(64), extraction_text_hash: 'b'.repeat(64),
};
const review = {
  id: id(4), report_id: report.id, document_id: report.document_id,
  reviewed_by_id: id(5), reviewed_at: '2026-11-01T12:00:00Z',
  source_file_hash: report.source_file_hash, extraction_text_hash: report.extraction_text_hash,
  review_workpaper_sha256: 'c'.repeat(64), outcome: 'not_reproduced',
  review_method: 'visual_original_scan', review_state: 'independent_observation_no_clearance',
  source_hold_cleared: false, claim_fact_approved: false,
};
const page = items => ({ items, offset: 0, limit: 25 });
const binding = {
  id: id(6), report_id: report.id, review_id: review.id, document_id: report.document_id,
  workpaper_document_id: id(7), workpaper_document_version: 1,
  workpaper_file_hash: review.review_workpaper_sha256,
  custody_state: 'managed_clean_document_record_linked',
  original_source_hold_cleared: false, claim_fact_approved: false,
};
test('all three bounded outcomes remain observations without clearance', () => {
  for (const outcome of ['not_reproduced', 'discrepancy_observed', 'inconclusive']) {
    const rows = parseOcrReviewReadback(page([{ ...review, outcome }]), report);
    assert.equal(rows[0].outcome, outcome);
    assert.equal(rows[0].source_hold_cleared, false);
  }
  assert.deepEqual(parseOcrReviewReadback(page([]), report), []);
  assert.equal(parseOcrWorkpaperReadback(binding, report, review).workpaper_file_hash, review.review_workpaper_sha256);
});
test('foreign, stale, self-reviewed and approval-bearing rows fail the entire page', () => {
  const invalid = {
    report_id: id(8), document_id: id(8), reviewed_by_id: report.reported_by_id,
    source_file_hash: 'd'.repeat(64), extraction_text_hash: 'd'.repeat(64),
    source_hold_cleared: true, claim_fact_approved: true,
    outcome: 'source_verified', review_method: 'machine_only',
    review_state: 'approved', reviewed_at: 'bad-date', review_workpaper_sha256: 'bad',
  };
  for (const [key, value] of Object.entries(invalid)) {
    assert.throws(() => parseOcrReviewReadback(page([{ ...review, [key]: value }]), report), key);
  }
  assert.throws(() => parseOcrReviewReadback(page([review, { ...review, id: id(9), claim_fact_approved: true }]), report));
});
test('malformed, duplicated, oversized and incorrectly paginated histories fail closed', () => {
  for (const payload of [null, {}, [], page([null]), page([review, review]),
    { ...page([]), offset: 25 }, { ...page([]), limit: 100 },
    page(Array.from({ length: 26 }, (_, i) => ({ ...review, id: id(i + 100) })))]) {
    assert.throws(() => parseOcrReviewReadback(payload, report));
  }
});
test('workpaper metadata cannot stand in for a different review, source, hash or clearance', () => {
  const invalid = {
    report_id: id(9), review_id: id(9), document_id: id(9),
    workpaper_document_id: report.document_id, workpaper_document_version: 0,
    workpaper_file_hash: 'd'.repeat(64), custody_state: 'content_verified',
    original_source_hold_cleared: true, claim_fact_approved: true,
  };
  for (const [key, value] of Object.entries(invalid)) {
    assert.throws(() => parseOcrWorkpaperReadback({ ...binding, [key]: value }, report, review), key);
  }
  assert.throws(() => parseOcrWorkpaperReadback(null, report, review));
});
