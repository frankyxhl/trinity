# Component spec: profiles — draft 0.1

Status: **draft, WO-001 boundary spec.** Requirements are unverified.
Laws that bind this component: LAW-04, 05, 06, 09 (METHOD.md §3).

## 1. Purpose

Give each usable (harness, account, model, billing) combination a short name, say how to read its credential and its quota, and pick a default when the caller does not name one.

## 2. Scope

In:

- Profile records: `name` (e.g. `claude:B`), `adapter`, `credential_source` (reference only), `model` (+ optional effort), `billing` (`subscription` | `metered`), `quota_source`, `label` (display, e.g. account nickname), `enabled`.
- `trinity profiles` listing (mockup): name, label, billing, current use, default marker.
- Default selection when the caller gives only a provider (`claude`): lowest current use among enabled profiles of that provider (mockup: "默认（本周用量最低）").
- Quota read for each profile: value, unit (weekly %, window %, money today), **read time**.

Out:

- Storing secrets (NG-05). Token files are made and rotated outside Trinity.
- Booking or leasing fleet seats (NG-02).
- Heavy-lock checks (dispatch core).

## 3. Boundary contract (draft)

| ID | Requirement |
| --- | --- |
| PRF-001 | A profile names its credential by source (file path or env var name). Trinity never reads the value except inside the adapter's child process. |
| PRF-002 | Profile listing and journal show `name` and `label`, never the credential source path's contents. Whether the source *path* itself may appear is OPEN-P4. |
| PRF-003 | A credential file with mode wider than 600/400 makes the profile unusable, with the reason shown (same rule as today's deepseek/openrouter wrappers). |
| PRF-004 | Each quota read carries `read_at`. A read older than the profile's freshness limit counts as unknown. |
| PRF-005 | Default pick ignores profiles whose quota is unknown, exhausted, or disabled; if none remain, dispatch stops (LAW-06) unless the caller names a profile. |
| PRF-006 | The chosen profile and the reason it was chosen (`named` / `default:lowest-use` / `override`) are journaled per node. |
| PRF-007 | Model ids live only in profile data (LAW-05); a profile with a retired id is refused at load. |
| PRF-008 | Profile data is layered: built-in examples in the repo (no real accounts), fleet pack outside the repo (LAW-09), project override last — same overlay idea as today's `~/.claude/trinity.json` + `.claude/trinity.json`. |

## 4. Initial profile set (from plan + mockup, illustrative)

| Profile | Adapter | Billing | Quota source |
| --- | --- | --- | --- |
| claude:A / B / C | claude-code, token from fleet-tokens | subscription | weekly % (source OPEN-P1) |
| codex | codex (Sol / Luna) | subscription | weekly % (read live, never snapshots — next-session note) |
| glm | droid or LiteLLM bridge (RSK-01) | subscription | window % |
| opencode | opencode Go deepseek | subscription | TBD |
| deepseek | direct API | metered | money today |
| agy | agy opus | subscription | TBD |
| minimax | droid M3 | subscription | TBD |

Account nicknames shown in the mockup are fleet data; they go in the fleet pack, not the repo (RSK-08).

## 5. Environment assumptions

- Fleet setup-tokens exist under the fleet token directory, one file per account, mode 600.
- A quota source exists per provider that can be read without side effects (usage.bob board, vendor CLI status, API balance endpoint).
- Clock is the host clock; read times compared in UTC.

## 6. Risks

| ID | Risk |
| --- | --- |
| PRF-R1 | Quota board staleness (seen 10-11) makes "lowest use" pick an exhausted account. |
| PRF-R2 | Token in a profile gets used by two runs at once; vendor may rate-limit per account. |
| PRF-R3 | The token file for an account is replaced (rotation) mid-run; continuing a session under a new token may fail (ADP-R2). |
| PRF-R4 | Repo examples drift from the fleet pack; people copy examples with real names. |
| PRF-R5 | "Lowest use" spreads load evenly and leaves no account with headroom for a P1 burst. |

## 7. Open items

| ID | Question |
| --- | --- |
| OPEN-P1 | Quota source per provider: usage.bob board, vendor CLI, or both with a freshness rule? |
| OPEN-P2 | Is "lowest weekly use" the right default rule, or should P1 work reserve a profile? |
| OPEN-P3 | Can a continued session switch profile? (Recommend no: a session stays on the profile that created it.) |
| OPEN-P4 | May the credential source path appear in listings/journal, or only the profile name? |
| OPEN-P5 | Fleet pack location and format; who edits it (station.bob? pfc?). |
