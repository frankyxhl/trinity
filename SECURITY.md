# Security Policy

## Supported Versions

Trinity supports security fixes for the latest released version and the current
`main` branch. Older releases are not routinely patched unless the maintainer
announces an exception for a specific vulnerability.

| Version | Supported |
| ------- | --------- |
| Latest release | Yes |
| `main` | Yes |
| Older releases | No |

## Reporting a Vulnerability

Please report suspected vulnerabilities privately. Do not open a public issue
for credential leaks, token handling bugs, command injection, release pipeline
weaknesses, or other security-sensitive findings.

Preferred channel:

1. Use GitHub's private vulnerability reporting flow for this repository, if it
   is available under the repository Security tab.
2. If private vulnerability reporting is unavailable, email
   `franky.xhl@gmail.com` with the subject prefix `[trinity-security]`.

Include enough detail to reproduce or assess the issue:

- Affected version, commit, or installation method.
- The vulnerable command, workflow, provider, or file path.
- Reproduction steps or a proof of concept.
- Expected impact, such as credential exposure, command execution, or privilege
  escalation.
- Whether the issue is already public or being coordinated elsewhere.

## Response Expectations

The maintainer aims to acknowledge security reports within 3 business days.
After acknowledgement, the maintainer will triage severity, ask for any missing
details, and coordinate a fix or disclosure timeline when the report is valid.

Please allow a reasonable remediation window before public disclosure. If the
report is not considered a vulnerability, the maintainer will explain the reason
or redirect it to a public issue when appropriate.

## Security Scope

In scope:

- Credential and token loading, redaction, and environment isolation.
- Provider wrappers and command execution paths.
- Installer, release, and GitHub Actions workflows.
- Review artifacts or logs that could expose secrets.

Out of scope:

- Vulnerabilities in third-party providers, CLIs, or model services unless
  Trinity's integration materially creates or worsens the risk.
- Social engineering, spam, denial-of-service load testing, or attacks against
  accounts and infrastructure not owned by this project.
