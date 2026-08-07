# Radio Outdoors Design Standard

This is the permanent UI standard for Radio Outdoors. New pages and components must use shared variables and classes in `static/css/style.css`, not page-specific or inline typography.

## Readability baseline

| Role | Standard |
| --- | --- |
| Base body text | 18px |
| Help and secondary text | 16px minimum |
| Form labels | 18px, bold |
| Inputs and selects | 18px |
| Buttons | 18px, semibold or stronger |
| Table text | 17–18px |
| Page titles | About 40px |
| Section headings | About 28px |
| Card headings | About 22px |
| Minimum button/click target | 44px high |

- Use a clean sans-serif font and comfortable line spacing.
- Maintain high contrast in normal, hover, focus, and disabled states.
- Use comfortable, consistent spacing between controls and sections.
- Make checkboxes and radio buttons larger where practical.
- Do not reduce typography below these standards without owner approval.
- Preserve semantic markup, keyboard navigation, visible focus, and assistive-technology behavior.

## Shared implementation

- Use the `--ro-` CSS variables in the final **Radio Outdoors Design System** section of `static/css/style.css`.
- Reuse shared button, card, form, table, map, and help-text classes.
- Do not add hard-coded inline font sizes.
- Required controls must visibly say **Required Field** without duplicating the marker.
- Application behavior must remain independent from visual styling.

## Maps and Google Places

- Google Maps InfoWindow and custom popup text must be readable at normal laptop distance.
- Operating Position names and popup titles must be prominent and bold.
- Advisory text must be at least 18px with generous line spacing.
- Places primary suggestion text should be approximately 18px.
- Places secondary text should be 16px.
- Places rows should be approximately 42–48px high with comfortable horizontal padding.
- Preserve Google icons, attribution, controls, and branding.

## Target environments

Design first for outdoor use, laptop and tablet screens, glare, and older eyes. Responsive layouts may reduce outer spacing, but must not reduce the typography or minimum click targets above.

## UI verification checklist

1. Check representative pages at laptop and tablet widths.
2. Confirm body, help, label, input, button, heading, and table sizes.
3. Confirm required-field markers and keyboard focus.
4. Inspect cards, tables, map popups, advisory text, and Places suggestions.
5. Confirm no clipping, unintended document overflow, or inaccessible controls.
6. Run Django checks and relevant automated tests.
