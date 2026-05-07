Feature: Review preset fan-out and preflight
  `trinity review --preset <name>` resolves a preset to a list of providers
  (required + optionally configured) and runs preflight before dispatching.
  These scenarios capture the four-case A/B/C/D boundary documented in
  TRN-2022-CHG (PR #44 round-3 panel review): optional providers without
  config are dropped; optional providers with a working CLI join the
  fan-out; optional providers with a broken CLI are NOT dropped — they
  fail preflight and abort the review like any required provider would.

  Scenario Outline: Optional provider preflight boundary
    Given required provider "glm" with CLI "/bin/sh"
    And the preset "p" has optional provider "codex" with CLI "<optional_cli>"
    When I resolve preset "p" against the config
    And I run preflight on the resolved fan-out
    Then the fan-out is "<expected_fanout>"
    And preflight overall ok is "<preflight_ok>"

    Examples:
      | optional_cli | expected_fanout | preflight_ok |
      | (no config)  | glm             | true         |
      | /no/such/bin | glm,codex       | false        |
      | /bin/sh      | glm,codex       | true         |

  Scenario: Required provider with broken CLI fails preflight
    Given required provider "glm" with CLI "/no/such/bin"
    And the preset "p" has no optional providers
    When I resolve preset "p" against the config
    And I run preflight on the resolved fan-out
    Then preflight overall ok is "false"
