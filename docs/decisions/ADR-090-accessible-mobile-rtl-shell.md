# ADR-090 — The bilingual operator shell remains accessible and navigable across mobile RTL/LTR layouts

Status: Accepted for Phase 12K implementation

## Context
Phase 12K established English/Persian localization and controlled RTL presentation across the active claims and governed-AI operator surfaces. The authenticated application shell, however, previously exposed its primary navigation only through a desktop sidebar that is hidden below the `lg` breakpoint. On mobile-width viewports this removed the primary route-navigation path even though the localized claim and AI surfaces themselves remained available.

The final Phase 12K sweep must close that usability gap without introducing a second navigation model, changing route semantics, mutating domain state, or weakening the established source/governance boundaries. Keyboard users also need a predictable way to reach the main content, identify the current route and see focus, while motion-sensitive users should not be forced through decorative transitions.

## Decision
1. Reuse the existing route inventory and translation keys for both desktop and mobile navigation; mobile navigation is a presentation of the same routes, not a separate workflow or permission model.
2. Provide a mobile navigation control below the desktop breakpoint with `aria-expanded`, `aria-controls`, a labelled modal drawer, explicit close control and Escape-to-close behavior. Closing with Escape or the explicit close control returns focus to the menu trigger.
3. Mirror the drawer edge with locale direction: left in English/LTR and right in Persian/RTL. Keep route marks, email addresses, claim references, IMO values, hashes and other controlled technical identifiers in explicit LTR islands where applicable.
4. Mark the active route with `aria-current="page"` in both desktop and mobile navigation.
5. Provide a keyboard-accessible skip link to a stable `main` target so operators can bypass repeated navigation.
6. Apply a shared visible `:focus-visible` treatment to interactive controls and respect `prefers-reduced-motion` for transitions and animations.
7. Opening/closing navigation, following routes and changing locale remain presentation/navigation actions only. They must not issue claim, workbench, AI or governance mutation requests.
8. Preserve English as the compatibility baseline and keep the existing localization authority boundary: no source evidence, AI/model output, reviewer text, correspondence, hashes, API enum values or governed records are rewritten by this shell work.
9. Verify the shell at a mobile viewport in both EN/LTR and FA/RTL, including drawer mirroring, current-route semantics, technical LTR islands, Escape/focus return and zero domain mutation. Existing desktop and English browser journeys remain required regression coverage.

## Consequences
- Authenticated users retain access to the full operator route set on mobile devices in both supported locales.
- Keyboard navigation gains an explicit skip path, visible focus and current-route semantics without changing business behavior.
- RTL/LTR shell direction becomes responsive as well as desktop-correct while technical identifiers remain readable.
- The shell does not gain new claim, AI, governance or authorization authority; all changes remain presentation and navigation concerns.
- More advanced modal focus trapping or additional assistive-technology refinements can be layered later without changing the domain boundary established here.
