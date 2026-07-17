# OMP substrate

Cerberus pins the OMP CLI version in `config/omp-version.json`. A live OMP review fails closed before model execution when the trusted executable's `--version` output does not match the pin. The child still runs with `env_clear()` and only the fixed trusted search path plus explicitly allowed environment.

The version probe is necessary but not sufficient: it cannot load or exercise `pi_natives`. The OMP path therefore also requires parseable `--mode json` lifecycle output with exactly one terminal `agent_end`, a non-error final assistant stop reason, and a request-bound `ReviewArtifact.v1` emission.

Install the current pin with:

```sh
bun install --global @oh-my-pi/pi-coding-agent@17.0.2
```

## Bumping the OMP pin

1. Update the version and install command together in `config/omp-version.json`.
2. Install that exact package version and confirm the coding-agent package and platform-native package report the same version.
3. Run at least five fresh direct and five Cerberus-shaped env-cleared `--mode json` probes that exercise a native tool. Retain a redacted receipt under `docs/evidence/`.
4. Run one live `cerberus review-diff --harness omp` review and validate its request-bound artifact.
5. Run `./scripts/verify.sh` and review the pin change before merge.

Do not repair or delete a native cache merely because its digest differs. Repair only after the canonical pinned binary reproduces a native-loader failure; then repeat the full lifecycle gate.
