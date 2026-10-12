# NUA platform foundation

Start with CURRENT_ARCHITECTURE_AUDIT.md, ADR-001-multiplatform-architecture.md and MULTIPLATFORM_READINESS_REPORT.md. Windows implementation is in `apps/windows`; platform queue primitives in `packages/platform-core`. Android is owned by Claude: see CLAUDE_HANDOFF.md.

This is a FOUNDATION review package, not a deployable venue release. Shared auth/offline/printer integration and certified hardware are outstanding. Do not use unsigned CI artifacts with real payments or real venue data.
