# Avrana onboarding

Read [AGENTS.md](AGENTS.md) first. It defines production boundaries, credential handling, evidence rules
and Git safety for every coding agent.

Then read [BOOTSTRAP.md](BOOTSTRAP.md), [architecture](docs/ARCHITECTURE.md), [services](docs/SERVICES.md),
[operations](docs/OPERATIONS.md) and [decisions](docs/DECISIONS.md).

This repository is canonical. Production is `/home/cody/avrana` and `/home/cody/docker` on host `avrana`;
`scripts/drift-check.py` shows where it differs from Git. A file being in Git does not prove it is
deployed, and nothing here deploys automatically.
