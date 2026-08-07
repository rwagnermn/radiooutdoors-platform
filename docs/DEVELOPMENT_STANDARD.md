# Radio Outdoors Development Standard

## Required workflow

1. Select one item from `BACKLOG.md`.
2. Mark it **In Progress**.
3. Reproduce the issue before editing code when applicable.
4. Identify and record the root cause.
5. Make the smallest coherent change.
6. Do not remove, rewrite, or reformat unrelated working functionality.
7. Run `python manage.py check`.
8. Run relevant automated tests.
9. Start the application and test the exact workflow when practical.
10. Report the root cause, files changed, tests run, results, and diff summary.
11. Mark the backlog item **Testing**.
12. Wait for browser and project-owner verification.
13. Only after owner approval, mark the item **Complete**, update `CHANGELOG.md`, and commit only the verified files.
14. Never push automatically. Push only after explicit approval.

An item is not complete merely because code was written or automated tests passed. **Complete** means the requested behavior was tested and the project owner approved it.

## Scope control

- Every bug, enhancement, or feature requires a unique backlog ID before implementation.
- Work on one backlog item at a time unless the project owner explicitly approves multiple items.
- Stop after the selected item is verified; do not begin adjacent work.
- Preserve all unrelated user changes in a dirty worktree.
- Do not create repair packages, installers, broad rewrites, or speculative refactors unless specifically requested.

## Verification report

Every implementation handoff must include:

- Backlog ID and status
- Reproduction and root cause
- Every file changed for that item
- Exact commands and workflows tested
- Test results
- Concise diff summary
- Known limitations or remaining verification

## Git workflow

- `main` represents verified and stable work.
- Use `feature/<short-name>` or `fix/<short-name>` for non-trivial work.
- Make small, focused commits.
- Never commit unrelated files.
- Never force-push without explicit approval.
- Before committing, show `git status` and the exact files to be included.
- Before pushing, state the branch and commits that will be pushed.
- Wait for explicit approval before pushing.

The `tools/push.bat` helper requires explicit file selection, shows the staged files, creates no commit when nothing is staged, displays the branch and outgoing commits, and requires `YES` before pushing.

## Development demo data

Create or refresh realistic local-only activity with:

```text
python manage.py create_demo_data
```

Each run recreates activity for the marker-owned `demo_` accounts, so repeated runs do not duplicate the data. The command uses the existing DEBUG-only development verification method and refuses to run when `DEBUG=False`.

Remove only those demo accounts, their related content, generated photo files, and unused explicitly prefixed demo Locations with:

```text
python manage.py remove_demo_data
```

Neither command runs automatically. Never enable these commands in production.

## Payment integration safety

- Payment processing is intentionally deferred until it is approved as a separate backlog item.
- Future payment flows must use hosted or provider-managed checkout.
- Radio Outdoors must never collect or store raw card numbers, expiration dates, CVV codes, or equivalent sensitive payment credentials.
- Payment SDKs, credentials, webhooks, checkout sessions, persistence models, and production controls require their own scoped design, security review, implementation, and verification.
