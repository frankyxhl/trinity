# Contract: transcript reader (原始记录读取器) — draft 0.2

Status: **draft, WO-002 contract.** Requirements are unverified until the independent acceptance cases exist.
Terms: `../method/METHOD.md` §2. Binds: LAW-04, 08, 11; ADP-012..014; VIEW-008, 011. Unified event schema: OPEN-05 (pointers in the journal, text only on demand).

## 1. Purpose

Turn one harness's native transcript, located by a journal ref, into the unified event list a view shows — on click, never at journal-write time — without inventing, hiding or leaking content.

## 2. Interface

```text
read(ref, harness, page?) -> result

ref     = transcript_ref | output_ref | reason_ref   # from the journal: path + offset or content hash
harness = the node's journal `harness` field          # picks the reader; the reader never guesses the format
page    = {from_seq?: int, max_events?: int}         # max_events ≤ 2000

result = {
  status:            "ok" | "gone" | "unreadable" | "ref_mismatch" | "withheld",
  events:            [event, …],                     # empty unless status = ok
  thinking:          "present" | "absent",
  next_seq:          int | null,                     # more events after this page
  redactions:        int,                            # matches replaced in this result
  found_missing_at:  time | null,                    # status = gone
  expected_expiry:   time | null                     # status = gone, from profile retention (PRF-009)
}

event = {
  seq:           int,                                # transcript order, from 0
  t:             time | null,                        # from the transcript only; never invented
  type:          "prompt" | "thinking" | "tool" | "output" | "heartbeat",
  text:          "…",                                # redacted
  thinking_form: "full" | "summary" | "encrypted",   # thinking events only
  tool:          {name, phase: "call" | "result"},   # tool events only
  raw:           true | false,                       # line the reader did not understand
  truncated:     true | false,
  raw_ref:       {path, offset}                      # where this event starts in the transcript
}
```

## 3. Contract

| ID | Requirement |
| --- | --- |
| RDR-001 | One reader per adapter, all with the interface above. The reader is chosen by the journal's `harness` field, never by inspecting the file. |
| RDR-002 | **On demand only.** A reader runs when a view asks (click, `show --events`, an open detail pane). Its output is never written to the journal or to disk; a view may keep it in memory while it is open. |
| RDR-003 | Events come in transcript order with increasing `seq`. `t` is the transcript's own time or `null`. |
| RDR-004 | A line the reader does not understand becomes an `output` event with `raw: true`; nothing is dropped (ADP-012). |
| RDR-005 | **Honest thinking.** `thinking_form` is `summary` when the harness gives a summary, `encrypted` when it gives ciphertext — then `text` is empty, never the ciphertext. When the transcript has no thinking at all, `thinking` is `absent` and no thinking events are returned (VIEW-011 labels it). Never `full` unless the transcript holds full text (LAW-11). |
| RDR-006 | **Gone.** If nothing exists at the ref's path, status is `gone`, `found_missing_at` is the time of this read, and `expected_expiry` is node start + the profile's `transcript_retention` when that is known, else `null` (ADP-014, VIEW-008). |
| RDR-007 | **Changed under the ref.** If the ref carries a content hash and the bytes at the ref do not match, or the offset is past the end, status is `ref_mismatch` with no events; the reader never guesses where the content moved. Permission or read errors give `unreadable`. |
| RDR-008 | **Redaction duty.** Every `text` (including raw lines and tool arguments and results) passes one shared redaction function before it is returned, and before any cut (RDR-009), so a secret on a cut boundary is never half-shown. Kinds, each replaced by `[redacted:<kind>]` and counted in `redactions`: (1) `key` — known provider key prefixes (for example `sk-`), at the start of the text or after a character that is not a letter or digit (so a prefix after `-`, `_`, `/` or `.` in a path slug matches, while words ending in the prefix, such as `risk-…` or `desk-…`, never match), followed by 16 or more characters from `[A-Za-z0-9_-]`; (2) `bearer` — the value after `Authorization:` or `Bearer `; (3) `private_key` — PEM private-key blocks; (4) `assignment` — the value in `NAME=value`, `NAME: value` or `export NAME=value` where NAME, split into segments at `_`, `-`, `.` and lower-to-upper case changes, has a whole segment that, ignoring case, is `KEY`, `APIKEY`, `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL`, `CREDENTIALS` or `AUTH`, or ends, ignoring case, in `PASSWORD`, `PASSWD`, `SECRET` or `TOKEN` (so `API_KEY`, `apiKey`, `x-auth-token`, `PGPASSWORD`, `GITHUBTOKEN` match; `max_tokens`, `Author`, `monkey` do not), or is an env name the profile declares (name kept, value masked); (5) `member` — the string value of a JSON or YAML member whose key matches the same names (`"api_key": "…"`); (6) `url_password` — the password in URL userinfo (`scheme://user:<masked>@host`); (7) `credential` — the profile's own credential value (RDR-013); (8) `entropy` — a run of 32 or more characters from `[A-Za-z0-9_+=-]` with letters and digits and at least 4.2 bits of entropy per character, and any pure-hex run longer than 64. **Hex rule:** a pure-hex run of 7 to 64 characters on its own is never masked by kind 8, so commit ids and content hashes survive; a secret that is bare hex of that length therefore survives (a known limit), while the same hex in an assignment or member (kinds 4–5) is masked. Best-effort (LAW-04); the bar is the leak-test fixture owned by the acceptance author. |
| RDR-009 | **Size limits.** One event's `text` is at most 64 KiB; longer text is cut, `truncated: true`, and the rest is reachable through `raw_ref`. One read returns at most 2000 events; `next_seq` pages on. Reason: long tool results (test logs) are common, and the detail pane must open quickly on large runs (VIEW-R2). |
| RDR-010 | **Heartbeat events** come only from progress or keep-alive markers inside the transcript. Journal heartbeat rows are not the reader's input; a view may merge them into the same timeline, labelled as journal rows. |
| RDR-011 | **Read-only.** A reader opens transcripts read-only, never moves, locks or deletes them, and reads a transcript that is still being written up to its last complete line. |
| RDR-012 | A reader never returns a credential source (path or env name) of the profile, only the redacted text (PRF-002). |
| RDR-013 | **The profile's own value without the core holding it.** The adapter's wrapper process, which reads the credential anyway (PRF-001), writes a verifier per profile: value length, a random salt, and SHA-256 of salt + value — never the value — to a mode-600 file in Trinity's state directory. The reader hashes only windows of that length that start at the beginning of a non-space run or right after one of `= : " ' / , ; @ ( [ { - _ .`, and only where the run has at least that many characters left; a window whose salted hash matches is masked (kind `credential`). This keeps the cost to a few hashes per token instead of one per character (about 64 K per 64 KiB event). A value glued to preceding letters or digits is not caught by this kind; kinds 1 and 8 still apply. The core and the reader never read the credential source. The verifier is replaced when the wrapper sees a different value. Reason: the value is high-entropy, so the salted hash does not reveal it, and exact matching catches it even with no pattern shape. |
| RDR-014 | **Secret-shaped paths.** Before the core appends a `transcript_ref`, `output_ref`, `reason_ref` or caller-supplied `override_ref`, it runs the path through the redaction function with the shape kinds only (1–7, not the entropy kind 8, so generated file names and id-bearing slugs are not withheld). If anything would be masked, the ref is not stored: the record holds `{"withheld": "secret_pattern"}` instead, the call itself still runs, and the reader returns status `withheld` with no events; the view says the pointer was withheld. Reason: relative paths still carry the vendor's project directory name, and a lookup table kept elsewhere would itself hold the secret. A false withhold that remains is accepted: it loses that pointer for good (the journal is append-only), and it is visible and countable as a `withheld` ref. |

## 4. Per-harness readers

What each reader starts from. "Known" items are visible in the baseline code; the rest are confirmed by fixture transcripts before the reader is built.

| Adapter | Transcript | Ref form | Thinking forms expected | Status |
| --- | --- | --- | --- | --- |
| claude-code | vendor JSONL session file | path + byte offset | full, encrypted | known (baseline locates these files) |
| anthropic-compat | same CLI, same JSONL | path + byte offset | full, encrypted, or absent per endpoint | known format; per-endpoint thinking by fixture |
| codex | vendor JSONL session record | path + byte offset | summary, encrypted | fixture needed |
| droid | vendor session record | to probe | to probe | fixture needed |
| agy | vendor session record | to probe | to probe | fixture needed |
| opencode | to probe (OPEN-A2) | to probe | to probe | fixture needed |
| deepseek-api | no vendor-side transcript (OPEN-R1) | path + byte offset of an adapter-written JSONL file | summary or absent | proposal |

## 5. Failure expectations

| Situation | Expected outcome |
| --- | --- |
| Vendor deleted the transcript | `gone` with the time of the read and, if known, expected expiry; the tree is unaffected (LED-010). |
| Vendor changed its format | Unknown lines arrive as `raw` output events; nothing is dropped; no crash. |
| Vendor compacted or rewrote the file | `ref_mismatch`; no events shown as if they belonged to the node. |
| Secret in a tool result | Replaced by `[redacted:<kind>]`, counted; a miss is a defect against the leak-test fixture. |
| A bare 40-digit hex secret | Survives (hex rule, RDR-008); recorded as a known limit, not a pass. |
| Transcript path carries a key-shaped directory name | Ref withheld (RDR-014); no event detail for that node; journal clean. |
| Huge tool output | Cut at 64 KiB with `truncated`; rest via `raw_ref`. |
| Transcript still growing (live) | Events up to the last complete line; the next read picks up from `next_seq`. |
| Encrypted thinking | One thinking event per block, `encrypted`, empty text, labelled in the view. |

## 6. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| RDR-R1 | The entropy rule redacts useful ids, a name rule over-masks ordinary words, or the hex exception lets a hex-shaped secret through | RDR-008 hex rule, key-prefix boundary and whole-segment name rule stated; leak-test fixture holds a hex-shaped secret in assignment and bare form |
| RDR-R5 | A path is falsely withheld and its pointer is lost for good | RDR-014 shape kinds only; residual false withholds are counted as `withheld` refs |
| RDR-R4 | The verifier file is read by someone who brute-forces it | Mode 600 and a salt per profile; a low-entropy credential's verifier can still be guessed — none yet |
| RDR-R2 | A reader is chosen by sniffing and misreads another harness's file | RDR-001 |
| RDR-R3 | In-memory view caches outlive the page and hold redacted text longer than needed | RDR-002 (memory only, for the open page) |

## 7. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-R1 | Direct HTTP API has no vendor transcript: may its adapter write a local JSONL transcript (outside the journal, kept per profile retention)? | Open — proposed yes; owner to confirm, since it makes Trinity hold transcript text for that adapter |
