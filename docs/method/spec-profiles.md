# Component spec: profiles — draft 0.2

Status: **draft, WO-001 boundary spec.** Requirements are unverified.
Terms: METHOD.md §2. Laws that bind this component: LAW-04, 05, 06, 09.

## 1. Purpose

Give each usable (harness, account, model, billing) combination a short name, say where its credential is read from and how long the vendor keeps its transcripts, and pick a default when the caller names only a provider.

## 2. Scope

In:

- Profile records: `name` (e.g. `claude:account-1`), `adapter`, `credential_source`, `model` (+ optional effort), `billing` (`subscription` | `metered`), `transcript_retention`, `label` (display), `enabled`.
- `trinity profiles` listing: name, label, billing, default marker.
- Default pick when the caller names only a provider: deterministic choice among enabled profiles of that provider; quota is not consulted.
Out:

- Storing or rotating secrets (NG-05).
- Booking external workers (NG-02).
- Running checks and writing check records (dispatch core, METHOD §5).

## 3. Boundary contract (draft)

| ID | Requirement |
| --- | --- |
| PRF-001 | A profile names its credential by a wrapper command it declares (`credential_source.wrapper`, the ready-made per-account command found on PATH). The adapter runs that command in place of the harness; the command alone reads the account's credential, so the core never reads the value. An env-var or file-path credential source, or a claude-code profile with no wrapper, is refused. |
| PRF-002 | Listings and the journal show `name` and `label` only — never the credential source (path or env name) and never its contents (settles OPEN-P4). |
| PRF-003 | A credential file with mode wider than 600/400 makes the profile unusable, with the reason shown (same rule as the baseline's compatible-endpoint wrappers). |
| PRF-004 | **Retired.** Profiles carry no quota read or freshness limit; existing quota fields are ignored. |
| PRF-005 | Default pick considers enabled profiles only and does not skip on quota; if none remain, dispatch stops with `check_failed` unless the caller names a profile. |
| PRF-006 | The chosen profile and why (`named` / `default:lowest-use` / `override`) are journaled per node. |
| PRF-007 | Model ids live only in profile data (LAW-05); a profile with a retired id is refused at load. |
| PRF-008 | Profile data is layered: neutral examples in this repo (no real accounts), then the private profile pack from a separate private repository (LAW-09; the repo never names its location — it is passed by env var or config at run time), then a project override. |
| PRF-009 | `transcript_retention` states how long the vendor keeps that profile's native transcripts (duration, or `unknown`). Readers use it to report expected expiry (ADP-014). |
| PRF-010 | A continued session stays on the profile that created it; asking to continue under another profile is refused (settles OPEN-P3). A continue that names only a provider reuses the session's profile and skips the default pick (PRF-005). A retry round on another profile (LED-004) starts a new session. |

## 4. Example profile set (neutral; real values live in the private pack)

| Profile | Adapter | Billing | Quota source kind |
| --- | --- | --- | --- |
| claude:account-1 / -2 / -3 | claude-code | subscription | shared status board or vendor CLI |
| codex | codex | subscription | vendor CLI (read live) |
| glm | droid | subscription | window % from vendor |
| opencode | opencode | subscription | TBD (OPEN-P1) |
| deepseek | opencode (subscription) / anthropic-compat or deepseek-api (metered) — OPEN-A3 | both | vendor CLI / API balance |
| agy | agy | subscription | TBD |
| minimax | droid | subscription | TBD |

## 5. Environment assumptions

- One credential file per account at the source the private pack names, mode 600. The account's wrapper command reads it; the core never does.
- Host clock; read times compared in UTC.

## 6. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| PRF-R1 | A stale status board makes "lowest use" pick an exhausted account | PRF-004, CHK-002 |
| PRF-R2 | Two runs use one account at once; vendor rate-limits per account | none yet (OPEN-P2) |
| PRF-R3 | Credential rotated mid-run; continuing the session fails | ADP-002 `auth_error` (surfaced, not hidden) |
| PRF-R4 | Repo examples drift from the private pack; someone copies real values into examples | WR-04 scan before public push |
| PRF-R5 | "Lowest use" leaves no account with headroom for urgent work | OPEN-P2 |

## 7. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-P1 | Quota source per provider and its freshness limit | **Retired**: dispatch does not read quota. |
| OPEN-P2 | Is "lowest use" right, or should urgent work reserve a profile? | Open — WO-002 |
| OPEN-P3 | Can a continued session switch profile? | **Decided by author:** no (PRF-010); reviewer to confirm |
| OPEN-P4 | May the credential source appear in listings/journal? | **Decided by author:** no (PRF-002); reviewer to confirm |
| OPEN-P5 | Profile pack file format (location decided: separate private repository) | Open — WO-002 |
