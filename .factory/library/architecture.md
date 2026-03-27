# Architecture

Target architecture, module boundaries, and simplification decisions for this mission.

**What belongs here:** target product shape, internal boundaries, design constraints, simplification goals.
**What does NOT belong here:** step-by-step feature checklists (use `features.json`) or runtime commands (use `.factory/services.yaml`).

---

- Cerberus stays a separate product from Thinktank for this mission
- Final product shape: one strict CLI for code review, centered on `cerberus review --repo <path> --base <ref> --head <ref>`
- Preferred deep boundaries:
  - request/workspace preparation from local refs
  - one shared review execution core
  - planner/router
  - merged reviewer configuration
  - repo-read tooling
  - verdict/output rendering
- Delete GitHub Action, HTTP API/server, Sprite/Fly, Node scaffolder, and shell-dispatch surfaces instead of preserving compatibility
- Use one reviewer configuration model; do not keep layered duplicate config sources alive
- Keep planner behavior deterministic under doubles and emit auditable planning artifacts
