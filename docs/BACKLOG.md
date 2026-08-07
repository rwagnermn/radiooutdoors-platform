# Radio Outdoors Backlog

Every requested bug, enhancement, or feature must be recorded here before implementation begins. Work on one item at a time unless the project owner explicitly approves multiple items.

| ID | Title | Status | Priority |
| --- | --- | --- | --- |
| B-001 | Fix My Adventures status control | Testing | High |
| B-002 | Fix Edit Adventure status control | Testing | High |
| B-003 | Default new Adventures to Public | Testing | High |
| B-004 | Default new Journal Entries to Public | Testing | High |
| B-005 | Improve Google Places autocomplete readability | Testing | Medium |
| B-006 | Apply global UI readability standards | Testing | High |
| B-007 | Show “Required Field” on required fields | Testing | Medium |
| B-008 | Create an Operating Position from the Add Adventure map | Testing | High |
| B-009 | Verify yellow Currently Operating pins | Open | High |
| B-010 | Verify red Advisory pins override yellow | Open | High |
| B-011 | Review macOS and Safari portability | Open | Medium |
| B-012 | Establish disciplined development workflow | Testing | High |
| B-013 | Center hamburger menu icons | Testing | Low |
| B-014 | Standardize Google Maps scroll lock | Testing | Medium |
| B-015 | Add original-size journal photo viewer | Testing | Medium |
| B-016 | Build Support page structure | Testing | Medium |
| B-017 | Integrate hosted payment provider | Open | Low |

## B-001 — Fix My Adventures status control

- **Description:** Make the status badge change Adventure status without triggering parent-row navigation.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Clicking Active/In Progress changes it to Completed; clicking Completed changes it to Active/In Progress; the row does not navigate; the updated badge is shown after returning to My Adventures.

## B-002 — Fix Edit Adventure status control

- **Description:** Provide a dedicated status action that does not submit or get overwritten by the normal edit form.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** The button label reflects current status; both transitions work; the user returns to Edit Adventure; an ordinary edit save does not reset status.

## B-003 — Default new Adventures to Public

- **Description:** New Adventures should reliably default to public while retaining manual private selection.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Newly created records default to `is_public=True`; users can explicitly save private Adventures; existing records remain unchanged.

## B-004 — Default new Journal Entries to Public

- **Description:** New Journal Entries should reliably default to public while retaining manual private selection.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Newly created records default to `is_public=True`; users can explicitly save private entries; existing records remain unchanged.

## B-005 — Improve Google Places autocomplete readability

- **Description:** Increase Places suggestion typography, padding, and row height globally while preserving Google icons and branding.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Primary text is approximately 18px; secondary text is 16px; rows are 42–48px high; Add New Location remains functional.

## B-006 — Apply global UI readability standards

- **Description:** Make shared typography, spacing, controls, tables, cards, and maps conform to the Radio Outdoors design standard.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Shared CSS tokens are used; specified minimum sizes are met; contrast and keyboard navigation are preserved; laptop and tablet layouts have no regressions.

## B-007 — Show “Required Field” on required fields

- **Description:** Required form controls must visibly identify themselves using consistent wording.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Required fields visibly say “Required Field”; markers are not duplicated; labels remain semantically associated with controls.

## B-008 — Create an Operating Position from the Add Adventure map

- **Description:** When a selected Location has no Operating Positions, allow creation from the map without leaving Add Adventure.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** The empty-state message appears; clicking the map creates a temporary marker and name prompt; save associates the position with the selected Location and selects it; Adventure creation can continue.

## B-009 — Verify yellow Currently Operating pins

- **Description:** Confirm currently operating map records use the intended yellow pin state.
- **Status:** Open
- **Priority:** High
- **Acceptance criteria:** A reproducible currently operating record displays yellow on every relevant map; automated or documented browser verification confirms it.

## B-010 — Verify red Advisory pins override yellow

- **Description:** Confirm an active Operating Advisory takes visual precedence over Currently Operating.
- **Status:** Open
- **Priority:** High
- **Acceptance criteria:** A record that is both current and under advisory displays red; removing the advisory restores the correct underlying state; relevant maps agree.

## B-011 — Review macOS and Safari portability

- **Description:** Review setup scripts, CSS, JavaScript, forms, and map workflows for macOS and current Safari compatibility.
- **Status:** Open
- **Priority:** Medium
- **Acceptance criteria:** Findings are documented; confirmed defects receive separate backlog IDs; supported setup and browser workflows are verified or limitations are recorded.

## B-012 — Establish disciplined development workflow

- **Description:** Create the project-management documents and safe Windows helpers that govern backlog, verification, Git, design, and product decisions.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** All six required documents exist under `docs`; start and check helpers run from the repository root; the push helper requires intentional file selection and confirmation; no application feature is changed; the project owner verifies the workflow.

## B-013 — Center hamburger menu icons

- **Description:** Center the three-line icon horizontally and vertically in every existing hamburger menu button without changing its dimensions or behavior.
- **Status:** Testing
- **Priority:** Low
- **Acceptance criteria:** Hamburger icons are visually centered; button dimensions, colors, borders, radii, hover states, focus outlines, and keyboard behavior remain unchanged.

## B-014 — Standardize Google Maps scroll lock

- **Description:** Configure every Google Map to capture wheel gestures while hovered and restore normal page scrolling outside the map.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Every application map uses `gestureHandling: "greedy"`; wheel gestures zoom hovered maps without scrolling the page; scrolling outside maps remains normal; touch/pinch and keyboard accessibility are preserved; marker and styling behavior are unchanged.

## B-015 — Add original-size journal photo viewer

- **Description:** Allow users to open journal photos at their original size and close the viewer to return to the same journal page.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Clicking or keyboard-activating a journal photo opens its original image in an accessible viewer; a clear Close control and Escape return to the unchanged journal page; upload, caption, cover-photo, and delete behavior remain unchanged.

## B-016 — Build Support page structure

- **Description:** Create the trustworthy, accessible Support Radio Outdoors page structure with expandable contribution information and disabled future-payment placeholders.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** The Support page contains the approved introductory, one-time, sustaining, infrastructure, and non-financial support content; disclosures are keyboard accessible; payment controls are visibly disabled; no payment SDK, request, credential, webhook, checkout, or payment model is introduced; payment safety guidance is documented.

## B-017 — Integrate hosted payment provider

- **Description:** Future, separately approved work to integrate provider-managed checkout without Radio Outdoors handling raw card data.
- **Status:** Open
- **Priority:** Low
- **Acceptance criteria:** Provider and legal requirements are approved first; checkout is hosted or provider-managed; no raw card number, expiration date, or CVV enters Radio Outdoors systems; credentials, webhooks, persistence, failure handling, privacy, and security are independently reviewed and tested.
