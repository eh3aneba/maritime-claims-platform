# Localization architecture — Phase 12K

## Boundary
Localization is presentation-only. Locale changes must never mutate ClaimFacts, evidence, AI governance state, coverage/liability/causation/recoverability assessments, reserves, settlement/payment state, legal rights, source documents, API enums, hashes or workflow identifiers.

## Foundation
- Supported locales: `en` and `fa`.
- `apps/web/src/lib/i18n.ts` owns the typed catalog.
- English defines `TranslationKey`; Persian is declared as `Record<TranslationKey, string>`, so a missing Persian catalog key is a TypeScript failure.
- `LocaleProvider` owns the current locale and updates `<html lang>` and `<html dir>`.
- First increment persists locale in bounded browser `localStorage` under `mcri.locale`; no database schema change is introduced.
- English is the safe default when no valid preference exists.

## RTL/LTR rules
Persian uses `dir=rtl`; English uses `dir=ltr`. App-shell placement, content offset and shared table alignment must follow direction.

Technical and controlled values remain LTR inside either locale, including:
- UUIDs and hashes;
- claim references and IMO-style identifiers;
- ISO dates where displayed as source values;
- email addresses, organization slugs and code-like values;
- H&M, P&I, GA, PA, AI and currency/technical abbreviations when direction would otherwise reduce readability.

Use `dir="ltr"` at the smallest relevant presentation boundary rather than forcing whole Persian sections back to LTR.

## Maritime terminology guidance
Translate interface concepts, not source evidence. Uploaded document text, survey reports, correspondence, extracted evidence and user-authored claim facts remain in their source language unless a separate explicit translation capability is approved.

Controlled terminology examples:
- Claims Workbench → میز کار پرونده‌ها
- claim handler → کارشناس خسارت
- candidate time-bar → time-bar کاندید / غیرقطعی
- authoritative task due date → موعد ثبت‌شده کار
- missing evidence → مدرک ناقص
- evidence conflict → تعارض شواهد

Do not translate `H&M`, `P&I`, `GA`, `PA`, `IMO` or `AI` into ambiguous Persian substitutes.

## First increment coverage
Implemented in the foundation increment:
- root locale provider and persistence;
- authenticated app shell and navigation;
- login;
- Claims Workbench;
- shared table direction behavior;
- browser coverage for English default, Persian switch, RTL mirroring, persistence, technical LTR isolation and no workflow mutation.

Remaining active surfaces are migrated incrementally using the same catalog/provider contract; no page-specific independent locale state is allowed.
