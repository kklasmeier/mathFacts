# Implementation plan

**Spec:** [Requirements/math-worksheet-spec.md](Requirements/math-worksheet-spec.md) version 1.18
**Code:** this folder (`/home/pi/Programming/mathFacts`)
**Run:** `http://192.168.1.26:8016` from `/home/pi/mathFacts` on the Pi

The spec is the product. This file is the order of work. A later slice starts only after the current slice's tests pass.

## Already decided

- One Flask app. Pages and `/api/...` routes share one process, one session, and one account check.
- gunicorn listens on `127.0.0.1:8017`. nginx site `mathfacts` listens on **8016** and proxies to gunicorn.
- Ports 80, 8080 (`networktraffic`), and 8888 (security cameras) stay as they are.
- Python 3.13. SQLite. Server-rendered HTML. No Node build step.
- Phase 1 is home-network HTTP. HTTPS is Phase 2, on this same nginx site.
- The first registered account is the Administrator.

## How the work is sliced

Each slice is a vertical piece that can be deployed. Tests from earlier slices stay in the suite and must still pass.

| Slice | What a person can do | Spec |
|---|---|---|
| 0 | Open the site. The service comes back after a reboot. | Deploy, section 3 |
| 1 | Register, stay signed in, sign out. The first account is the Administrator. | 5.11 |
| 2 | Add a child, build a sheet, set columns and rows, regenerate, print one Letter page. | 5.1, 5.2, 5.12.1 |
| 3 | Reprint, delete, rate a sheet. | 5.3, 5.4 |
| 4 | Inactivate an account, reset a password, read the sign-in log. | 5.11.5, 5.13 |
| 5 | Plans, next sheet from a stage, progress, badges. | 5.5, 5.6, 5.7 |

Slices 0–4 are Phase 1A. Slice 5 is Phase 1B. Phase 2 (HTTPS, invites, email) and Phase 3 (custom badges, A4, co-parent sharing, import) wait until slice 5 is in use.

## Tests

Unit tests are the gate between slices. The suite grows with the app and is run as a whole before every deploy. A new slice that breaks an older test is not done.

```bash
python -m pytest
```

That command uses a temporary SQLite database, makes no network calls, and does not need nginx or the Pi. It is the check that later work still matches earlier behavior.

### Rules

- Every slice adds tests in the same change as the code.
- Tests already in the suite stay. They are removed only when the spec itself changes, and the test is updated in that same change.
- Pure functions (parsing, fact pools, layout math, advancement, badges) are tested without the web server.
- Pages are tested with the Flask test client: status, redirects, and the words on the page.
- A request from account B for account A's child, sheet, or other record returns **404**. One test per ID-taking route, added when the route is added.
- Passwords and remembered-sign-in secrets are asserted to be stored as hashes (the reset password is the encrypted exception in the spec).
- The fast suite does not launch a browser. Print layout math is unit-tested. A separate browser-to-PDF check, from spec 5.2.1, runs before slice 2 is called done and again when print layout changes.

### What the suite protects

| Area | Tests that must keep passing |
|---|---|
| Number specs | `"0-3, 5, 10"` parses to a sorted unique list. Bad input returns a clear error. |
| Fact pools | Addition, subtraction drops negatives, division drops ÷0, reverse order, doubles, sums to 10. |
| Filling the page | 100 spaces of `0–10 × 2` uses 11 facts, ten of them 9 times and one 10 times. The same fact does not share a side with itself. Regenerating with a new seed changes the arrangement. |
| Fit on one page | Font size and cell size for a few across × down cases, with and without a badge row. Below 10pt raises the legibility warning and still returns a size. |
| Sign-in | First account is admin. Duplicate email or username is rejected. A short password is rejected. The remembered cookie signs the user in. Sign-out requires the password next time. A wrong remembered secret revokes that token. |
| Isolation | Cross-account IDs return 404. |
| Sheets | Reprint returns the same problems. Regenerate on an issued sheet keeps the number. Regenerate is refused on a completed sheet. Deleting an issued sheet does not change progress. |
| Ratings | Performance and support are required. Aids count toward advancement. Two of the last three at Good or better is ready to advance, including sheets done with an aid. |
| Plans and badges | Added in slice 5. Next sheet opens the builder and does not save by itself. A child can receive many sheets on the same stage. Badges are awarded once and are not removed when a sheet is deleted. |
| Themes and layout | Appearance cookie is accepted. Narrow width is a later browser check, not a unit test. |

Slice 5 adds the plan and badge tests. It does not weaken the sheet, rating, or sign-in tests.

### Layout of the tests

```
tests/
  test_specs.py          number specs and fact pools
  test_slots.py          repeats, spacing, seeds
  test_fit.py            one-page size math
  test_children.py       child CRUD, 10-child limit, archive, typed-name delete (slice 2)
  test_web.py            health, sign-in redirect, headers, static files (slice 0-1)
  test_db.py             schema, migrations, WAL, foreign keys (slice 0-1)
  test_security.py       password rules, hashing, tokens (slice 1)
  test_auth.py           register, sign-in, remembered devices, sign-out, password change (slice 1)
  test_isolation.py      cross-account 404s (slice 2: children, sheets, preview)
  test_sheets.py         builder, preview matches saved sheet, regenerate, print pages (slice 2)
  helpers.py             shared form helpers for route tests
  test_ratings.py        rating form and advancement counts
  test_plans.py          slice 5
  test_badges.py         slice 5
  test_admin.py          slice 4
```

Files arrive with the slice that creates the behavior. `pytest` collects whatever is present, so the command does not change from slice to slice.

## Slices

### 0 — Skeleton and deploy

Flask app, config, SQLite file, gunicorn unit, nginx site `mathfacts`.

- `GET /health` returns 200.
- Visiting `/` redirects to sign-in once slice 1 exists. Until then it shows a plain holding page.
- Reboot brings the site back.
- Test: the app factory creates a client and `/health` is 200.

Deploy this slice first so the path to the Pi is proven before the product code depends on it.

### 1 — Sign-in

Register, sign in, remembered device, sign out, forced password change after an admin reset (the reset screen itself is slice 4; the forced-change page exists here so the flag works).

Tests: the sign-in rows in the table above, plus the device cookie and a failed sign-in that does not reveal whether the account exists.

### 2 — Children and sheets

Children CRUD (archive, restore, delete). Builder with live preview. Across and Down. Regenerate before save. Print view for Letter, portrait and landscape, vertical and horizontal. Repeats when there are fewer facts than spaces, with no shared sides.

Tests: parser, pools, slot filler, fit math, and a saved sheet whose stored problems match the preview.

### 3 — History and ratings

List, detail, reprint, reprint with answer key, delete, clean up unfinished, rate. Home shows the current child's unfinished count and five newest sheets. The ready-to-advance rule is implemented; its banner, badges, and the cleanup-age setting are later slices.

Tests: reprint identity, regenerate rules, delete of an issued sheet, rating required fields.

### 4 — Administration

Accounts list (counts only, no child names), inactivate, reactivate, reset password, sign-in log, audit log, site settings.

Tests: inactive account cannot sign in, reset forces a new password, admin cannot open another family's sheet, admin cannot inactivate their own account.

### 5 — Plans, progress, badges

System plan copies, wizard, next sheet into the builder, stay on a stage across many sheets, progress pages, badge award and banner.

Tests: pair rules, review mix, advancement (2 of the last 3, aids count), badge once-only, banner of 4 plus "+N more" when more than 5 are pending, deleting an issued sheet returns its badges to pending, deleting a completed sheet does not.

## Deploy

From this folder, after `pytest` passes:

1. Copy the app to `pi@192.168.1.26:/home/pi/mathFacts`, excluding the virtualenv, the database, and secrets.
2. On the Pi, install dependencies into a virtualenv in that directory.
3. Install the systemd unit (gunicorn on `127.0.0.1:8017`) and the nginx site (listen 8016).
4. Restart gunicorn and reload nginx.
5. Open `http://192.168.1.26:8016` from another device.

The secret key and the database live only on the Pi. They are not copied back into this folder and not committed.

## Done means

- The slice's behaviors match the spec sections named above.
- `python -m pytest` passes, including every test from earlier slices.
- The Pi serves the slice at `http://192.168.1.26:8016`.
- Ports 80, 8080, and 8888 still serve their existing sites.
