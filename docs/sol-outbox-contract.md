# Jobsearchpal → Sol repo integration spec

Spec for changing Jobsearchpal so it publishes approved jobs to a private GitHub repo. Sol is a cloud agent in Claude Duet. It reads the repo, fills in application forms and writes back which jobs were applied to.

## 1. Purpose and roles

- **Jobsearchpal** writes approved jobs, each with its generated resume and cover letter, to `main`. It reads application status back from the `status` branch.
- **Sol** reads `main` and writes status records to the `status` branch only. Sol never pushes to `main`.
- Each branch has exactly one writer, so the two sides can never conflict.

## 2. Repository

- A private repo owned by a dedicated GitHub account, for example `jobsearchpal-outbox`.
- Two branches:
  - `main`: job folders, written by Jobsearchpal.
  - `status`: status records, written by Sol. Sol creates this as an orphan branch on first write. Jobsearchpal must handle the branch not existing yet.
- No branch protection rule should block direct pushes to `status`.
- Add a short `README.md` on `main` that points to this contract.
- Add `.gitattributes` with `*.pdf binary` and `*.docx binary`.
- Nothing secret is ever committed: no tokens, passwords, government ID numbers or dates of birth.

## 3. Layout on `main`

```
README.md
applicant.json                      # optional, see section 6
jobs/
  <slug>/
    job.json                        # required
    resume.pdf                      # required
    cover-letter.pdf                # required if one was generated
    cover-letter.txt                # optional plain text, for forms with a text box
    resume.docx                     # optional, for sites that reject PDF
    withdrawn.json                  # optional, see section 5
```

**Slug format:** `YYYY-MM-DD-<company>-<title>-<id>`
- The date is the date the job was approved.
- `company` and `title` are lowercased. Any run of characters other than `a-z0-9` becomes a single `-`. Leading and trailing `-` are trimmed. Each part is cut to 30 characters.
- `id` is Jobsearchpal's own job id, made slug-safe the same way.
- The whole slug is at most 100 characters and is unique.
- Example: `2026-10-27-acme-corp-senior-devops-engineer-js4821`

**File size:** each file must be under 10 MB, the upload limit on Sol's side. Aim for under 2 MB.

## 4. `job.json` schema (v1)

| Field | Type | Req | Notes |
|---|---|---|---|
| `schema_version` | int | yes | `1` |
| `id` | string | yes | Jobsearchpal job id; stable across syncs |
| `slug` | string | yes | Same as the folder name |
| `title` | string | yes | |
| `company` | string | yes | |
| `apply_url` | string (https URL) | yes | Where the application form lives |
| `posting_url` | string (https URL) | no | The listing, if it differs from `apply_url` |
| `source` | string | no | Job board name |
| `location` | string | no | |
| `workplace` | `"remote"` \| `"hybrid"` \| `"onsite"` | no | |
| `employment_type` | string | no | For example `"full-time"` |
| `salary` | string | no | As listed |
| `description` | string | no | Full posting text; helps answer form questions |
| `approved_at` | string (ISO 8601 with offset) | yes | |
| `files` | object | yes | `{ "resume": "resume.pdf", "cover_letter": "cover-letter.pdf" }`; paths are relative to the folder; `cover_letter` may be `null` |
| `notes` | string | no | Anything Chris wants Sol to know for this job |

Example:

```json
{
  "schema_version": 1,
  "id": "js4821",
  "slug": "2026-10-27-acme-corp-senior-devops-engineer-js4821",
  "title": "Senior DevOps Engineer",
  "company": "Acme Corp",
  "apply_url": "https://jobs.example.com/acme/4821/apply",
  "source": "Example Board",
  "location": "United States",
  "workplace": "remote",
  "employment_type": "full-time",
  "salary": "$130k-$150k",
  "approved_at": "2026-10-27T15:04:00-04:00",
  "files": { "resume": "resume.pdf", "cover_letter": "cover-letter.pdf" }
}
```

## 5. Commit rules for Jobsearchpal (on `main`)

- **Add, don't rewrite.** Each approved job gets a new folder. Jobsearchpal never deletes a job folder and never rewrites `main`'s history.
- **Regenerated documents:** Jobsearchpal may replace files in a job's folder only while Sol has no status record for that job (see section 7). Use commit message `job: update <slug>`.
- **Withdrawing a job:** add `withdrawn.json` with `{"withdrawn_at": "<ISO 8601>", "reason": "<optional>"}` instead of deleting the folder. Sol skips any job that has this file.
- **One commit per job:** `job: add <slug>`. A daily batch is fine as long as each job still gets its own commit.
- **Pushing:** run `git pull --rebase origin main` before `git push origin main`. Never force-push.
- **Idempotency:** before writing, check whether a folder with that job `id` already exists. If it does, don't add it again.

## 6. Optional `applicant.json` (on `main`)

These are standard answers Sol reuses across forms. Every field is optional. Leave out anything Chris wants to be asked about each time.

```json
{
  "schema_version": 1,
  "name": "", "email": "", "phone": "", "city_state": "",
  "links": { "linkedin": "", "github": "", "portfolio": "" },
  "work_authorization": "", "needs_sponsorship": false,
  "earliest_start": "", "salary_expectation": "",
  "voluntary_disclosures": "ask"
}
```

- Never include passwords, SSN or other government IDs, date of birth, or bank details. Sol will not enter these and will hand those steps back to Chris.
- `voluntary_disclosures` covers demographic, disability and veteran questions. Its values are `"ask"` (the default) or `"decline"`.

## 7. The `status` branch contract (written by Sol)

**Path:** `status/<slug>.json`, with one file per job. Sol creates the file once. Sol only changes it if the status later moves from `skipped` or `closed` to `applied`.

| Field | Type | Req | Notes |
|---|---|---|---|
| `schema_version` | int | yes | `1` |
| `job_id` | string | yes | Matches `job.json` `id` |
| `slug` | string | yes | |
| `status` | `"applied"` \| `"skipped"` \| `"closed"` | yes | `skipped`: Chris chose not to apply. `closed`: the posting no longer accepts applications. |
| `at` | string (ISO 8601 UTC) | yes | When the status was reached |
| `confirmation` | string | no | The site's own confirmation reference or message, max 200 characters |
| `note` | string | no | Short plain-text note from Sol, max 500 characters |

Example:

```json
{
  "schema_version": 1,
  "job_id": "js4821",
  "slug": "2026-10-27-acme-corp-senior-devops-engineer-js4821",
  "status": "applied",
  "at": "2026-10-28T14:22:10Z",
  "confirmation": "Application received, ref ACM-99812"
}
```

**When Sol writes a status record:**
- Sol writes `applied` only after Chris has approved submitting that application and the site has shown that it went through.
- Each commit adds or changes one file, with the message `status: <status> <slug>`.

## 8. Status sync in Jobsearchpal

1. On a schedule, and on demand, run `git fetch origin status`. If the branch doesn't exist yet, stop and try again next time.
2. List the files with `git ls-tree --name-only origin/status status/` and read each one with `git show origin/status:status/<file>`. Jobsearchpal never checks out or commits to `status`.
3. For each record:
   - Parse it as JSON.
   - Check it against the schema above, and ignore unknown fields.
   - Match `job_id` to the local job.
   - Set the local status. `applied` wins over `skipped` or `closed`.
4. Treat every field as untrusted data:
   - Never execute it.
   - Escape it when rendering.
   - Cap string lengths.
   - Skip and log any record that is malformed or has no matching job.
5. Applying the same record twice must not change anything. Store the last-synced commit SHA so unchanged runs can be skipped.

## 9. GitHub auth in Jobsearchpal

- Add a GitHub sign-in screen. Either of these works:
  - A GitHub App or OAuth app using the device flow.
  - A fine-grained personal access token pasted by the user. Limit it to this one repo, with **Contents: read and write** and nothing else.
- The signed-in identity is the dedicated account.
- Store the token in the OS keychain or an encrypted local store. Never commit it, log it or show it after entry.
- Push over HTTPS using that token, or use a deploy key with write access on this repo only.
- Sol's access is set up separately: Chris connects the same dedicated GitHub account to Claude and grants the Claude GitHub App access to this repo only. Sol never needs Jobsearchpal's token.

## 10. Acceptance criteria

- [ ] Approving a job in Jobsearchpal produces, within one sync, a `jobs/<slug>/` folder on `main` with a valid `job.json` and the files it names. All files are under 10 MB.
- [ ] Re-running the publisher creates no duplicate folders and no empty commits.
- [ ] Withdrawing a job adds `withdrawn.json`; nothing is deleted.
- [ ] Running against a repo with no `status` branch succeeds with no changes.
- [ ] A hand-made `status/<slug>.json` with `"status": "applied"`, pushed to `status`, changes that job's status to "applied" in Jobsearchpal on the next sync.
- [ ] A malformed or unmatched status file is logged and skipped, and the sync continues.
- [ ] No token or other secret appears in the repo, in logs or in commit history.
- [ ] The GitHub sign-in screen can connect, disconnect and show which account is connected.
