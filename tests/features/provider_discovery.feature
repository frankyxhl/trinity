Feature: Provider discovery
  A provider is "usable" only when it has BOTH a config entry in
  `~/.claude/trinity.json` (or the project overlay) AND a matching agent
  file at `~/.claude/agents/trinity-<name>.md`. Anything else is reported
  as "unregistered" with the specific reason. discover.py is what
  `/trinity status` calls under the hood.

  Background:
    Given a temporary discovery setup

  Scenario: A provider with both config entry and agent file shows as usable
    Given a global config with provider "glm" CLI "droid exec"
    And an agent file for provider "glm"
    When I run provider discovery
    Then provider "glm" status is "usable"

  Scenario: A provider with config but no agent file shows as missing_agent
    Given a global config with provider "codex" CLI "codex exec"
    When I run provider discovery
    Then provider "codex" status is "missing_agent"

  Scenario: A provider with agent file but no config shows as missing_config
    Given an agent file for provider "gemini"
    When I run provider discovery
    Then provider "gemini" status is "missing_config"
