# Acceptance cases: credential leak set and honest transcripts (ACC-200 .. ACC-227)

Companion to `ACCEPTANCE.md` (conventions, doubles and seams are in its section 0). This file defines the **bar** for "no secret in any output" (the requirement says pattern redaction is best-effort, so the bar must be written down: it is the must-catch list in L1 plus the surfaces in L2).

## L0. Fixture secrets

All values are fake and built at test time from parts, so that no real-looking token is stored in the repository. S1 to S6 are zero-filled for readability; because zero-filled bodies never trip an entropy rule, S7 and S8 use random bodies (generated at test time from a seeded generator, the seed recorded in the report).

| Name | Construction | Shape |
| --- | --- | --- |
| S1 | `sk-test-` + 32 times `0` | vendor-style API key |
| S2 | `Bearer ` + `test-token-` + 32 times `0` | authorisation header value |
| S3 | `TEST_API_KEY=` + `test-` + 32 times `0` | environment assignment line (also `*_TOKEN=`, `*_SECRET=`, `*_PASSWORD=`) |
| S4 | JSON member `"api_key": "test-` + 32 times `0` + `"` | structured config or tool argument |
| S5 | `https://user:` + `test-pw-` + 16 times `0` + `@example.invalid/` | password inside a URL |
| S6 | the contents of the profile's credential file (`test-cred-` + 32 times `0`) | the profile's own credential value |
| S7 | `sk-test-` + 40 random characters from `[A-Za-z0-9]` | vendor-style key with a high-entropy body |
| S8 | `TEST_SECRET=` + 40 random lowercase hex digits (an assignment); and the same 40 hex digits alone on a line (bare) | hex-shaped secret; the bare form looks like a git object id |

Variants of one value for the scanner: raw; JSON-escaped; URL-encoded; HTML-entity-encoded; base64 of the raw value; the first 12 and last 12 characters alone (a partial leak is a leak).

## L1. The bar

**Must-catch** (the reader's redaction has to remove these wherever they appear in an event text; a hit is a failure): S1, S2, S3, S4, S5, S6, S7 and the assignment form of S8 as raw text, including when they sit inside a longer line, at the very start or end of a text, in a tool-call argument, inside a stack trace, and repeated 100 times in one event.

**Contract bar.** The reader's pattern list (RDR-008) covers S1 to S5 by kinds 1 to 6 (known prefixes, bearer values, PEM blocks, assignments with generic names such as `*_API_KEY=`, `*_TOKEN=`, `*_SECRET=`, `*_PASSWORD=`, JSON/YAML members, URL userinfo) and S6, the profile's own credential value, by the salted verifier (RDR-013; kind 7): the wrapper writes the verifier and the core and reader never read the credential source (NG-05, PRF-001). ACC-226 checks the verifier.

**Report-only** (known limits of best-effort redaction; the case records the result and never fails on it, but the *journal, logs, argv and the profile listing must still be clean*, because those surfaces never hold text at all): the bare form of S8 (a 7 to 64 digit hex string survives by design so that commit ids and hashes do, RDR-008 hex rule); a secret split across two lines; base64, URL-encoded or HTML-entity variants of a value in event text; a value with zero-width characters inserted.

**Scanner** `scan(root_list, secret_set)`: reads every file and every captured byte stream below the given roots as bytes, decodes entity, URL and base64 layers one level deep, and reports each (file or stream, variant) hit. Hits in files named in the explicit allow-list for a case (the credential file itself, vendor-owned fake transcripts, which are test inputs) are ignored; everything else is a failure.

## L2. Surfaces

Journal file(s); prune log; error log; Trinity state and cache directories; temp files; stdout and stderr of every Trinity command; `trinity profiles`; `trinity tree` (default and expanded); `trinity show --events`; the local web page (HTML, every JSON/stream response, response headers, page title); child process argv sampled during calls; child environment; crash output; and, if the owner adopts the adapter-written local transcript for the direct-API adapter (OPEN-R1), that file (it holds full text outside the journal, so it is scanned like any vendor fixture except that it is Trinity's own output and gets no allow-list entry).

---

### ACC-200 Guard the guard: the scanner finds a planted leak
Covers: LAW-04, SUC-03
Given: a control directory in which S1 appears raw, JSON-escaped, URL-encoded, entity-encoded, base64 and as first/last 12 characters, each in a different file.
When: the scanner runs.
Then: every one of the seven hits is reported.
Observable: seven reported hits with file names.
Fails if: fewer than seven. A leak suite whose scanner misses a variant proves nothing; this case runs first and gates the others.

### ACC-201 Secret in a native transcript, every event type
Covers: LAW-04, ADP-012, LED-008, LED-009, VIEW-R3
Given: for each adapter, a fixture transcript with S1..S7 and the assignment form of S8 planted in a `prompt` event, a `thinking` event, a `tool` input, a `tool` output and an `output` event, one per event (40 plantings per adapter).
When: a run records a call that points at the transcript, then the reader is asked for events, through the library, `trinity show <run>/<node> --events` and the web detail pane.
Then: the journal holds no part of any secret; the events returned by the reader, printed by the CLI and shown by the web page contain none of the must-catch values (redacted in place, with a visible mask `[redacted:<kind>]`, and the result's `redactions` count equals the number of plantings); event count and order are unchanged by redaction; the `raw_ref` of a redacted event still resolves to the unredacted source bytes in the vendor file (the file is not modified).
Observable: scan of the journal and of all view outputs is empty; the transcript fixture file's hash is unchanged; event count equals fixture event count.
Fails if: any hit, or a redacted event was dropped instead of masked, or the transcript file was rewritten.
Note: S3 generic names, S4, S5 and S6 are RDR-008 kinds 4 to 7.

### ACC-202 Secret in stderr
Covers: LAW-04, ADP-002, ADP-012
Given: a fake harness that writes S1, S3 and S5 to stderr and exits in a way that maps to `unknown`.
When: the call runs.
Then: the core's error log holds the last 2 KB of stderr with the secrets masked; the journal holds none of it; the CLI message shown to the caller contains none of it.
Observable: error log tail; journal scan empty; CLI output scan empty.
Fails if: the unmasked value reaches any surface, or stderr text reaches the journal.

### ACC-203 The 2 KB cut never exposes half a secret
Covers: LAW-04, ADP-002
Given: stderr of 6 KB where S1 begins 20 bytes before the 2 KB boundary of the kept tail (so the cut falls inside the key), and a second case where the key ends exactly at the final byte with no newline.
When: the call exits as `unknown`.
Then: redaction happens on the full stream before the tail is taken, or the cut is moved so that no fragment longer than 8 characters of the key survives.
Observable: scan for first-12/last-12 variants and for any 9-character run of the key's tail: empty.
Fails if: a key fragment survives at the cut. Also: a multi-byte UTF-8 character at the cut leaves the kept tail valid UTF-8.

### ACC-204 Secret on other exit classes
Covers: LAW-04, ADP-002
Given: stderr containing S1 for each of `harness_error`, `auth_error`, `quota_exhausted`, `timeout`, `interrupted`, `session_not_found`.
When: each call ends.
Then: the exit class is journaled; the stderr text is journaled nowhere; any reason text shown to the caller is masked.
Observable: journal and CLI scans empty.
Fails if: any hit.

### ACC-205 Secret in the profile path, env name and file
Covers: LAW-04, PRF-001, PRF-002, PRF-003
Given: a profile whose credential source is a file in a directory named after S1 (path contains the key shape) and a second profile whose source is an environment variable whose *name* contains a secret-shaped suffix; both contain S6 as their value.
When: `trinity profiles` runs; a call uses each profile; the file mode of one is changed to wider than 600 so the profile becomes unusable; one credential file is removed so a load error occurs.
Then: no listing, journal line, tree line, error message or unusable-profile reason shows the path, the variable name or S6; the reasons say what is wrong ("mode too wide", "source missing") without naming the source.
Observable: scan of all L2 surfaces for the path string, the variable name and S6: empty.
Fails if: any hit, including inside an exception message.

### ACC-206 Secret in a malformed profile pack
Covers: LAW-04, PRF-001, PRF-008
Given: a profile pack file with a syntax error on a line that contains S4.
When: the pack is loaded.
Then: the load error names the problem and a line number, never the line's text.
Observable: error text scan empty.
Fails if: the offending line is echoed.

### ACC-207 Secret in the core's own failure output
Covers: LAW-04, NG-05
Given: a profile with S6 loaded; the core is made to fail in four ways (an adapter raises, the journal directory is read-only, the clock seam raises, an unhandled exception is injected after profile load).
When: each failure happens.
Then: the traceback, crash output and any core dump text (where the platform writes one) contain none of S6, no environment dump, no argv of the child.
Observable: scan of the captured stderr and of the error log.
Fails if: any hit. A traceback that prints local variables, or a debug repr of the resolved profile that includes the credential, fails here.

### ACC-208 Maximum verbosity stays clean
Covers: LAW-04, NG-05
Given: the most verbose logging option the CLI offers (and the debug environment switch, if any).
When: a full run with S6 loaded and S1 planted in stderr, transcripts and the prompt.
Then: nothing in L2 holds a secret.
Observable: scan.
Fails if: verbose mode prints the child environment, the argv, the resolved credential or request headers.

### ACC-209 Argv and environment of the child
Covers: LAW-04, ADP-005, ADP-006
Given: a profile with a credential delivered by environment variable or file; the parent environment also holds an undeclared variable `UNDECLARED_PLANT=` + S1.
When: the call runs while a sampler records the full argument list of every process in the child's tree every 10 ms, and the fake harness writes its own argv and environment *names* to a capture file.
Then: no sampled argv contains S6; the child receives the declared variable and the allow-list, not `UNDECLARED_PLANT`; the wrapper does not echo the value to stdout or stderr.
Observable: sampler output scan; captured env names; stdout/stderr scan.
Fails if: any argv hit; the undeclared variable reaches the child; a shell trace (`set -x`) of the wrapper shows the value.
Note: the sampler must cover at least 20 samples inside the call; a call shorter than that is padded by the double.

### ACC-210 Secret inside the prompt the caller sends
Covers: LAW-04, LED-009, ADP-012
Given: a prompt (text and file forms) that contains S1.
When: the call runs and its events are viewed.
Then: the journal holds no prompt text; the `prompt` event is masked in every view; the core's logs hold no prompt.
Observable: scan.
Fails if: the prompt text is stored or shown unmasked.

### ACC-211 Secret in caller-supplied free-text fields
Covers: LAW-04, LED-009, CHK-004, LED-004, DSP-017
Given: S1 placed in each caller-supplied field the core accepts: step name, node label, run name, `override_ref`, `reason_ref` (retry), any `--note`-like option. The override reason itself is a closed code (CHK-004, DSP-003) and is tested in ACC-113: a secret placed in the code position is refused as an unlisted code.
When: each is written.
Then: `step` and `label` holding S1 are refused `bad_request` naming the field, never stored masked (DSP-017); a `step` or `label` of 64 characters is accepted, of 65 is refused, of 0 is refused; `override_ref` and `reason_ref` are pointers (a ref, never text), and a value shaped like text or like a secret is refused or stored as a withheld ref (RDR-014); no other field accepts text; the journal never holds S1; no field accepts prompt-sized text (fixture: 100 KB is refused).
Observable: journal scan; behaviour per field recorded (refused / withheld) with the field name and the limit.
Fails if: any field stores the raw value or a masked form of it, any field accepts 100 KB of text, or a 65-character `step` is accepted.

### ACC-212 Secret in a path the journal must store
Covers: LAW-04, LED-009, LED-R1, RDR-014, LED-016, RDR-R5
Given: a transcript whose directory name contains S1 (a project slug built from a key-like string), so that `transcript_ref.path` would carry the secret; the same for an `output_ref` and a `reason_ref`; and, as controls, a transcript with an ordinary path, a path holding a generated 40-character random file name (entropy-shaped, no key prefix), and a path with a directory `my-task-runner-implementation` or `risk-` followed by 20 letters.
When: the call is recorded, then the reader and both views are asked for the node.
Then: for the secret-shaped refs the journal holds `{"withheld": "secret_pattern"}` instead of the path; the call itself still runs and ends normally; the reader returns status `withheld` with no events; the CLI and web detail say the pointer was withheld; no secret and no path fragment reaches the journal, the error log or a view; the three controls keep their refs and resolve normally (RDR-014 applies the shape kinds 1 to 7 only, never the entropy kind, and the key-prefix boundary of RDR-008); every withheld ref can be counted from the journal by its `withheld` marker.
Observable: journal scan and the ref record; reader status; view text.
Fails if: the path with the key is written, the call is refused or fails because of the path, the reader returns events from a withheld ref, a different strategy (relative path, hashed lookup) is used, or a control ref is withheld.

### ACC-213 Summary-only thinking is labelled, never faked
Covers: ADP-013, LAW-11, VIEW-011, RSK-11
Given: for each adapter that can emit it, a fixture where thinking is only a summary ("SUMMARY-ONLY-MARKER ..."), a fixture where thinking is encrypted (a 64-byte random blob), a fixture where thinking is full text, and a fixture with no thinking at all.
When: the reader returns events and the CLI and web show them.
Then: `thinking_form` is `summary`, `encrypted`, (full), `absent` respectively; the summary text carries the label "摘要" next to every place it appears; the encrypted blob is never decoded, never printed as text, and carries the label "已加密"; absence shows "无思考记录"; no summary is concatenated, merged with or placed under the heading of full thinking; the word "full" or its equivalent never appears next to a summary.
Observable: reader output field; CLI and web text around the marker string; for the encrypted fixture, scan that the blob's bytes (raw, hex, base64) are absent from view output.
Fails if: a summary appears without its label in any view, an encrypted blob is displayed or guessed at, or an absent thinking shows an empty list as if the node had thought nothing and had no record.

### ACC-214 Deleted transcript shows gone and when
Covers: ADP-014, LAW-11, VIEW-008, LED-R1
Given: a finished node whose transcript is then deleted by the test; the profile states a retention of 30 days (a second profile says `unknown`).
When: the reader and the views are asked for events at t1, and again at t2 later.
Then: the reader returns `gone` with the time it was found missing; with the 30-day profile it also returns an expected expiry time; with `unknown` retention it says the expiry is unknown and does not invent one; the CLI and web text read "原始记录已不存在 · since <time>" and, when known, "vendor retention ended <time>"; the tree, states and numbers are unchanged; an empty event list is never shown in its place.
Observable: reader fields; exact view strings; byte-equality of the tree rendering before and after the deletion.
Fails if: an empty list, an error page, a crash, a missing time, or a fabricated expiry.

### ACC-215 No transcript text is cached by Trinity
Covers: LAW-08, LED-009, ADP-012
Given: events viewed for a node whose transcript holds the marker strings `PROMPT-MARKER`, `THINK-MARKER`, `TOOL-MARKER`, `OUTPUT-MARKER`.
When: the transcript is then deleted.
Then: scanning Trinity's journal, state, cache, temp and log directories finds none of the markers; the reader reports `gone` and does not serve a remembered copy.
Observable: scan; reader result after deletion.
Fails if: any marker is found outside the vendor fixture, or the deleted transcript is still readable through Trinity.

### ACC-216 A transcript that comes back is read again
Covers: ADP-014, LAW-11
Given: the deleted transcript of ACC-214 is restored byte-for-byte.
When: events are requested again.
Then: the events are returned; the earlier `gone` result was not stored anywhere that overrides a later successful read.
Observable: events returned.
Fails if: `gone` persists.

### ACC-217 Web view surfaces
Covers: VIEW-006, LAW-04, VIEW-R3
Given: the web view opened on a journal and transcripts holding S1..S6 and on a run whose profile loaded S6.
When: the page, every script, every JSON or stream response, every response header (including cookies and server banners) and the page title are captured and scanned, including entity-encoded forms.
Then: no secret in any captured byte; no cookie, no authorisation header is set or required; page source holds no inline data blob with unmasked event text.
Observable: scan of captured traffic; request log shows no credential header.
Fails if: any hit, any `Set-Cookie`, or any request needing a credential to load the page.

### ACC-218 Full-corpus sweep (the pilot's leak condition)
Covers: SUC-03, LAW-04, LAW-08, RSK-02
Given: one temporary root in which every other case of this file has run, with the allow-list limited to the credential files and the vendor fixture transcripts.
When: the scanner runs over the entire root, including hidden files, temp files, session store, caches and logs, plus the captured output of every command executed.
Then: zero hits for S1..S6 and for all variants of the journal-visible kinds; zero transcript markers (ACC-215) in the journal.
Observable: scanner report is empty and lists the number of files and bytes scanned (a report that scanned zero files fails).
Fails if: any hit or an empty scan.

### ACC-219 Redaction limits are recorded, not hidden
Covers: LAW-04
Given: the report-only shapes from L1 planted in event text.
When: the reader returns them.
Then: the case writes the outcome per shape (masked or not) into the run report; it does not fail on them; the journal, logs, argv and listing scans stay clean regardless.
Observable: the report table; the clean scans.
Fails if: the report is missing, or the clean scans fail.

### ACC-220 Redaction does not corrupt neighbours
Covers: ADP-012, LAW-11
Given: events whose text contains ordinary strings that merely resemble the patterns ("sk-learn", "the key is on the table", base64 test data not forming a key, a long hex git id).
When: the reader runs.
Then: ordinary text is not masked (a bounded false-positive rate: at most 1 in 20 of the fixture lines); masking leaves the rest of the line intact; the mask is visible, so a reader sees that something was removed.
Observable: diff of fixture vs output lines.
Fails if: more than the bound is masked, or a mask is invisible.

### ACC-221 Prune log and error log are clean and bounded
Covers: LAW-03, LAW-04, LED-013
Given: the stderr of ACC-202 in the error log; a prune run.
When: the 90-day prune runs on the journal and the error-log retention runs.
Then: the prune log lists run ids, a count and a time only; error-log entries older than 90 days are removed and newer ones kept; neither file holds a secret.
Observable: file contents; scan.
Fails if: either file carries text beyond that, or the prune log is itself pruned.

### ACC-222 Redaction happens on read, never at write
Covers: ADP-012, LAW-08
Given: a spy on the reader.
When: a run is recorded and no view is opened; then a view is opened and one node is clicked.
Then: the reader is called 0 times during recording and exactly once for the clicked node; opening the tree does not call it.
Observable: spy counters.
Fails if: transcript text is read at journal-write time or at tree-load time.

### ACC-223 Uncertain input is raw, never dropped, never leaked
Covers: ADP-012, RSK-03, LAW-04
Given: a transcript with 10 recognisable lines, 5 unknown-kind lines (valid JSON of an unknown type), 3 lines of malformed JSON and 2 lines of binary garbage; S1 sits in an unknown line and in a malformed line.
When: the reader runs.
Then: 20 events come out; the 10 unknown or malformed lines are `output` events marked `raw`; S1 is masked in them as well.
Observable: counts, the raw marker, scan.
Fails if: an event is dropped, the reader raises, or raw events skip redaction.

### ACC-224 Journal records never hold text, whatever the harness sends
Covers: LED-009, LED-008, LAW-08
Given: a harness double that emits a 5 MB output and 5 MB of thinking and tool text per call, with marker strings spread throughout.
When: ten such calls run.
Then: the journal stays small (each record at most 4 KiB, DSP-017) and contains no marker string.
Observable: maximum line length; scan for markers.
Fails if: any line exceeds the bound or holds a marker.
Note: the bound is 4 KiB per journal line (DSP-017).

### ACC-225 The entropy rule and the hex exemption are both exercised
Covers: RDR-008, RDR-R1, LAW-04
Given: event text holding S7 (random-bodied key) on its own, S7 with no known prefix (40 random characters in a log line), the assignment form of S8 (`TEST_SECRET=` + 40 hex digits), the bare form of S8, a real-looking git object id (40 hex digits) in a commit line, a 7-digit short id, a 64-digit content hash, a 65-digit hex string.
When: the reader returns the events.
Then: S7 with the prefix and the assignment form of S8 are masked (must-catch); the 40-character random string with no prefix is masked by the entropy rule; hex strings of 7 to 64 digits in plain text (git ids, content hashes) survive unmasked; a 65-digit hex string is treated as high-entropy and masked; the bare S8 outcome is recorded in the run report (ACC-219) and does not fail the case.
Observable: masked or not, per fixture line; `redactions` count.
Fails if: S7 or the assignment form of S8 survives, a 7 to 64 digit hex id is masked, or the 65-digit string survives.
Note: the hex-shaped outcome is the RDR-008 hex rule: 7 to 64 hex digits alone survive, the same hex in an assignment or member is masked, a longer run is masked.

### ACC-226 The profile's own credential value is matched without the core holding it
Covers: RDR-013, RDR-008, RDR-R4, PRF-001, NG-05
Given: two profiles, each with a credential value of random shape (no known prefix, 24 characters, not entropy-flagged by length) written to its credential file; the wrapper run for each; a transcript that carries profile A's value in plain text, inside a longer line, at the start and end of a text, right after each of `=`, `:`, `"`, `'`, `/`, `,`, `;`, `@`, `(`, `[` and `{`, next to profile B's value, and once glued to preceding letters (`abc` + value, no separator); and one 64 KiB event made of a single non-space run.
When: the reader returns the events; then profile A's credential is changed and the wrapper runs again; then the file system and the process of the core and the reader are inspected.
Then: both values are masked as `[redacted:credential]` wherever they sit; the verifier file for each profile is mode 600, holds a length, a salt and a hash, and neither the value nor any 6-character piece of it; the two profiles have different salts (the same value under both would give different hashes); after the change the old value is no longer masked as a credential (it may still be masked by shape rules) and the new value is; a spy on file opens shows the core and the reader never open the credential source, only the verifier; a value that is not in the profile (a random string of the same length) is not masked as `credential`; the value glued to preceding letters is not caught by this kind (RDR-013), though kinds 1 and 8 still apply if its shape matches; the 64 KiB single-run event costs a few hashes, not one per character (a spy on the hash call counts at most 64 for the event, against about 65 000 for a window at every offset).
Observable: reader output; verifier files (mode, contents scan); open-file trace of the core and reader.
Fails if: the value survives, the verifier file holds the value or has a wider mode, the two profiles share a salt, the old value stays masked as `credential` after replacement, the core or reader opens the credential source, or the hash count for the single-run event grows with its length.

### ACC-227 Key prefixes need a boundary and name rules match whole segments
Covers: RDR-008, RDR-R1, RDR-R5, LAW-04
Given: event text holding (a) `sk-` plus 20 letters at the start of the text, after a space, after `=`, after `"` and after `(`; (b) the same 20 letters behind `risk-`, `desk-`, `disk-` and in the words `my-task-runner-implementation`; (c) assignments `API_KEY=`, `apiKey=`, `x-auth-token:`, `db.password=`, `CLIENT_SECRET=`, each with a 12-character value; (d) lines `max_tokens: 4096`, `Author: someone`, `monkey=banana`, `keyboard=us`, `tokenizer=bpe`.
When: the reader returns the events.
Then: every (a) form is masked as `[redacted:key]`; no (b) text is changed; every (c) value is masked with the name kept; no (d) line is changed; `redactions` counts only the masks of (a) and (c).
Observable: output text per fixture line; `redactions` count.
Fails if: a (b) word is masked, a (d) value is masked, a (c) value survives, or an (a) key survives.
