Feature: Session heartbeat
  `session.py heartbeat <output_file>` parses the JSONL output written by
  a background dispatch agent and reports current state — line count,
  last assistant text or tool use, completion status. The skill uses this
  for the proactive progress-update loop.

  Scenario: Heartbeat against a missing output file reports FILE_NOT_FOUND
    Given a missing heartbeat output file path
    When I run heartbeat against the output file
    Then the heartbeat output indicates "FILE_NOT_FOUND"

  Scenario: Heartbeat against an output file with assistant tool use reports the last tool
    Given an output file with an assistant message using tool "Bash" with input summary "pytest tests/"
    When I run heartbeat against the output file
    Then the heartbeat output mentions "Bash"
    And the heartbeat output mentions "pytest tests/"
