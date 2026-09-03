# Security Policy

AIE is experimental software and **not a security certification or production trust product**.

## Reporting

For sensitive security defects, do not publish exploit details in a public issue. Contact the maintainer privately through the GitHub account associated with this repository and provide a minimal reproduction, affected version/commit, and impact.

## Security invariants

The reference implementation is intended to fail closed for unresolved identity, authority, revocation, replay, policy, budget, and critical-extension conditions. Any change that weakens these invariants requires explicit security review and conformance changes.

## Secrets

No production credentials, signing keys, SPIRE trust material, OAuth tokens, or other secrets should be committed to the repository. Test certificates must be ephemeral fixtures only.
