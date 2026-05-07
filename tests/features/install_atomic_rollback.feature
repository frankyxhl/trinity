Feature: Install atomic rollback
  `install.py register` adds a provider config entry; `install.py
  unregister` removes it. The skill's `/trinity install` command wraps
  these with atomic rollback semantics: if any of the install steps fail
  (CLI lookup, agent-file copy, smoke test), the partial state is rolled
  back. This feature exercises the register/unregister CLI surface that
  the skill calls.

  Background:
    Given an empty global config

  Scenario: register followed by unregister removes the provider config entry
    When I register provider "myprov" with CLI "myprov-cli"
    Then the global config contains provider "myprov"
    When I unregister provider "myprov"
    Then the global config does not contain provider "myprov"

  Scenario: unregister on a provider that does not exist is a no-op
    When I unregister provider "ghost"
    Then the global config does not contain provider "ghost"
