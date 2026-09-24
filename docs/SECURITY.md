# Security and sensitive material

This is operational guidance, not a new security audit. It incorporates BookStack pages 37, 42, 59, 69, 76 and 77 with the production boundaries verified in this session.

Secrets remain in live `.env` files, service secret directories, application databases, host credential stores and recovery archives. Document locations and variable names only. Never migrate secret values, user/session/token tables, personal journals, health records, viewing history, profiles or authentication exports into this repo. A private GitHub repository is not a secrets vault.

Authentik provides shared identity, but application access is not universally SSO. Historical Jellyfin guidance describes local accounts provisioned through Authentik rather than an OIDC session; do not assume deleting an identity revokes every application credential. Verify the service-specific offboarding path before acting. September worker maintenance applied 13 blueprints for the first time; its exact authorization/configuration effects still need an audit.

Some services use Docker socket proxies. The presence of a proxy or read-only filesystem does not establish adequate authorization; no broad privilege claim is made here. Avoid direct Docker socket access in new code. Do not execute secret-generation, offboarding, restart or backup tooling merely to test source imports.

LAN binding is not a substitute for a verified firewall policy. Jellyfin and Home Assistant use host networking. Historical firewall proposals and audit results must not be described as applied without fresh evidence. See [networking](NETWORKING.md).

Before staging, review exact paths, text diffs, secret patterns, private keys, personal records, sizes, binaries and symlinks. Review source fixtures as well as code. Run `python3 scripts/review_git_content.py --staged` after staging; automated checks complement manual review and cannot prove absence of all sensitive data.
