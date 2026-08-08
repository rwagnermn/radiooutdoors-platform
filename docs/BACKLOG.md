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
| B-018 | Improve Member onboarding and profiles | Testing | High |
| B-019 | Improve staff Member verification and management | Testing | High |
| B-020 | Preview Member and Journal photos before save | Testing | Medium |
| B-021 | Create rich development test data and refine header identity | Testing | Medium |
| B-022 | Establish Radio Outdoors and Adventure Book brand hierarchy | Testing | Medium |
| B-023 | Add selective trademark marking and visible Member Adventure actions | Testing | Medium |
| B-024 | Standardize compact Journal browsing lists | Testing | Medium |
| B-025 | Populate missing development demo photos | Testing | Medium |
| B-026 | Add a primary Location photo | Testing | Medium |
| B-027 | Add licensed Wikimedia Location defaults | Testing | Medium |
| B-028 | Manage Default Location Images in staff UI | Testing | Medium |
| B-029 | Refine compact Journal selection tables | Testing | Medium |
| B-030 | Redesign Radio Outdoors interior pages | Testing | High |
| B-031 | Fix the shared interior-page header panorama | Testing | High |

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

## B-018 — Improve Member onboarding and profiles

- **Description:** Standardize the existing Home CTA family, provide a concise post-registration Welcome page, and add optional optimized Member profile photos.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Verified registration signs the Member in and opens the Welcome page; its three actions work; Home CTA typography is consistent; Members can upload, replace, remove, and display an optimized profile photo; existing Members receive a consistent placeholder; QRZ identity and email privacy remain protected.

## B-019 — Improve staff Member verification and management

- **Description:** Add staff-only existing-Member QRZ verification, a development-only verification override, and accessible row action menus to Member management.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Staff can reverify an existing callsign through the shared QRZ service; development profiles can only be overridden by staff while DEBUG is enabled; public verification rules remain strict; management rows show photos and clear verification status; actions are consolidated into an accessible hamburger menu.

## B-020 — Preview Member and Journal photos before save

- **Description:** Add a shared client-side Load/Change/Clear preview workflow for Member and Journal photo selections without uploading before normal form submission.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Selected Member and Journal images can be previewed, changed, and cleared locally; saved media remains unchanged until the normal Save action; canceling creates no records; existing duplicate-photo protection remains intact.

## B-021 — Create rich development test data and refine header identity

- **Description:** Provide repeatable, development-only realistic Member activity data and display signed-in Member identity as callsign followed by first name.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Each `demo_` Member has approximately 10 varied Adventures and 15 realistic Journals; reruns do not duplicate data; removal cannot delete non-demo user content; production verification remains unchanged; the header shows `CALLSIGN - First Name`, callsign-only fallback, and an explicit Follower identity.

## B-022 — Establish Radio Outdoors and Adventure Book brand hierarchy

- **Description:** Apply the approved Radio Outdoors, Adventure Book, Adventure, and Journal terminology to the Home page, public Member story collections, concise Help copy, and product documentation.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Home clearly states the product tagline without added marketing clutter; public Member profiles present only public Adventures under a dynamic possessive Adventure Book heading; management remains My Adventures; internal models, routes, tables, classes, forms, and migrations remain unchanged.

## B-023 — Add selective trademark marking and visible Member Adventure actions

- **Description:** Mark prominent Radio Outdoors branding with the TM symbol and add an explicit View Adventure affordance to every public Member Adventure Book entry.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Trademark marking is selective and never uses the registered symbol or marks Adventure Book; every Member Adventure entry has an always-visible, keyboard-accessible, touch-friendly View Adventure action; card presentation and public visibility behavior remain unchanged.

## B-024 — Standardize compact Journal browsing lists

- **Description:** Replace oversized multi-entry Journal cards with one shared, responsive, compact table/list presentation while preserving full Journal stories on their detail pages.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Public and management Journal lists show compact date/time, prominent title, one-line summary, photo count, and an always-visible View Journal action; management actions remain available; mobile rows stack cleanly; Lessons Learned and Journal detail presentation remain unchanged.

## B-025 — Populate missing development demo photos

- **Description:** Add safe DEBUG-only tooling that copies optimized random local images into missing demo Journal photo slots and assigns supported Adventure covers.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Existing photos and source files are preserved; only missing demo photo slots are populated; images are copied under ignored media storage and resized; missing/invalid sources fail safely; supported missing Adventure covers are assigned; Location population uses the single-photo support tracked in B-026.

## B-026 — Add a primary Location photo

- **Description:** Add one optional optimized Location image with preview-before-save, replacement/removal, compact list display, detail display, map-popup support, and development-only demo population.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Existing Locations remain valid without photos; authorized add/edit forms validate and optimize one image and support preview, replacement, and removal; list/detail/map surfaces show a photo or branded placeholder without oversized rows; demo tooling fills only clearly development-only missing Location photos; media remains ignored and all tests pass.

## B-027 — Add licensed Wikimedia Location defaults

- **Description:** Provide a small curated Wikimedia Commons fallback-image library, kept separate from Member Location photos, with validated reusable licenses, local optimized storage, type mapping, and accessible attribution.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Member photos always win; installed type defaults appear for no-photo Locations; the built-in placeholder remains the final fallback; unclear licenses are rejected; attribution remains accessible; files are stored locally without hotlinking or entering Git; checks and tests pass.

## B-028 — Manage Default Location Images in staff UI

- **Description:** Add a discoverable staff-only menu entry and compact management/edit workflow for default Location images, attribution, replacement, and enable/disable controls.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Only staff can access the menu and routes; all configured defaults appear with thumbnail, credit, license, status, and accessible action menu; image and attribution edits work with preview-before-save; disabling preserves the record and falls through to the built-in placeholder; Member Location photos retain priority; actual port-8000 HTML is verified.

## B-029 — Refine compact Journal selection tables

- **Description:** Bring every multi-entry Journal selection list to Contacts-table density while retaining a distinct table area, one-line summaries, obvious actions, and responsive stacking.
- **Status:** Testing
- **Priority:** Medium
- **Acceptance criteria:** Journal rows reuse the Contacts table container/cell treatment; desktop date, title, and summary stay on one compact line with clean ellipsis; separators and the dark-green header distinguish the list from surrounding content; all multi-entry lists use the shared partial; obsolete Journal-card list markup/styles are removed; mobile records remain compact and usable.

## B-030 — Redesign Radio Outdoors interior pages

- **Description:** Bring interior pages into the Home page's outdoor visual family through one shared header/background/table/story/gallery/footer system without changing the Home hero or application behavior.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** Shared interior pages use the forest-green, cream, orange, outdoor design language; record tables are compact and visibly actionable; Adventures and Journals retain story presentation; Contacts remain dense; photo galleries preserve varied aspect ratios and batch preview supports removing individual selections; decorative horizons vary without adding dead space; Home remains unchanged apart from inheriting the shared site header; desktop, tablet, signed-in/out, checks, and tests pass.

## B-031 — Fix the shared interior-page header panorama

- **Description:** Replace the nearly opaque interior-header overlay with one shared compact forest-green-to-mountain panorama treatment while preserving the existing logo, navigation, identity, and account behavior.
- **Status:** Testing
- **Priority:** High
- **Acceptance criteria:** The project-owned mountain/forest photograph is plainly visible without a hard seam; logo and navigation remain readable, compact, centered, consistent across interior pages, and overlap-free for signed-in/out desktop and tablet layouts; the Home hero remains unchanged.
