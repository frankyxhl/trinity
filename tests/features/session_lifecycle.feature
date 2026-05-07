Feature: Session lifecycle
  Trinity persists per-instance session state in `.claude/trinity.json`.
  The session.py CLI is the canonical write path for the dispatch flow.

  Background:
    Given a temporary project dir

  Scenario: Writing a session entry persists provider key, session id, and task summary
    When I write a session entry "glm:auth" with session_id "abc-123" and task "implement JWT"
    Then the session file contains key "glm:auth"
    And the session entry "glm:auth" has session_id "abc-123"
    And the session entry "glm:auth" has task_summary "implement JWT"

  Scenario: Clearing a session entry removes it but preserves siblings
    Given a session entry "glm:auth" with session_id "abc-123" and task "implement JWT"
    And a session entry "codex" with session_id "def-456" and task "review auth"
    When I clear the session entry "glm:auth"
    Then the session file does not contain key "glm:auth"
    And the session file contains key "codex"
