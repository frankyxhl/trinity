# Contract: transcript reader (原始记录读取器) — draft 0.1

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
  status:            "ok" | "gone" | "unreadable" | "ref_mismatch",
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
| RDR-008 | **Redaction duty.** Every `text` (including raw lines and tool arguments and results) passes one shared redaction function before it is returned. Patterns: known provider key prefixes; `Authorization`/bearer headers; private-key blocks; assignments to the env names the profile declares (value replaced, name kept); long high-entropy strings — except pure hex of 7–64 characters, so commit ids and content hashes survive. A match is replaced by `[redacted:<kind>]` and counted in `redactions`. Best-effort (LAW-04); the bar is the leak-test fixture owned by the acceptance author. |
| RDR-009 | **Size limits.** One event's `text` is at most 64 KiB; longer text is cut, `truncated: true`, and the rest is reachable through `raw_ref`. One read returns at most 2000 events; `next_seq` pages on. Reason: long tool results (test logs) are common, and the detail pane must open quickly on large runs (VIEW-R2). |
| RDR-010 | **Heartbeat events** come only from progress or keep-alive markers inside the transcript. Journal heartbeat rows are not the reader's input; a view may merge them into the same timeline, labelled as journal rows. |
| RDR-011 | **Read-only.** A reader opens transcripts read-only, never moves, locks or deletes them, and reads a transcript that is still being written up to its last complete line. |
| RDR-012 | A reader never returns a credential source (path or env name) of the profile, only the redacted text (PRF-002). |

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
| Huge tool output | Cut at 64 KiB with `truncated`; rest via `raw_ref`. |
| Transcript still growing (live) | Events up to the last complete line; the next read picks up from `next_seq`. |
| Encrypted thinking | One thinking event per block, `encrypted`, empty text, labelled in the view. |

## 6. Risks

| ID | Risk | Caught by |
| --- | --- | --- |
| RDR-R1 | The entropy rule redacts useful ids, or the hex exception lets a hex-shaped secret through | RDR-008 pattern list; leak-test fixture includes a hex-shaped secret |
| RDR-R2 | A reader is chosen by sniffing and misreads another harness's file | RDR-001 |
| RDR-R3 | In-memory view caches outlive the page and hold redacted text longer than needed | RDR-002 (memory only, for the open page) |

## 7. Open items

| ID | Question | Status |
| --- | --- | --- |
| OPEN-R1 | Direct HTTP API has no vendor transcript: may its adapter write a local JSONL transcript (outside the journal, kept per profile retention)? | Open — proposed yes; owner to confirm, since it makes Trinity hold transcript text for that adapter |
