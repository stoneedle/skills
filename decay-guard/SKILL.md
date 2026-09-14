---
name: decay-guard
description: Keep code changes simple, proportional, and on one real path. Use for every implementation, refactor, review, or deletion, especially when work crosses modules or public seams, changes ownership or persisted state, adds an abstraction or generic capability, proposes compatibility, migration, versioning, fallback, retry, recovery, or other extra behavior, uses a runtime mock, or expands beyond the requested feature.
---

# Decay Guard

Choose the simplest implementation that delivers the requested behavior. A deep module may be complex inside; its owned seam stays narrow.

## Follow The Request

- For a non-trivial change, name the outcome, target, and non-goals. For a small local change, edit directly.
- Derive scope from the request, current code, real consumers, and observed runtime state. Possibility is not evidence.
- Implement one current path. Treat versions, ordering races, hashes, idempotency, projections, fault tolerance, backups, compensation, retries, fallbacks, compatibility, and extra modes as new features unless the requirement or real state demands them.
- Record a useful new feature for later; keep it out of the current implementation and contracts.
- Keep one owner, source, writer, and lifecycle for each rule or fact. Put necessary complexity behind that owner instead of making callers coordinate it.
- Add a public abstraction or generic option only for a real second consumer or implementation, or an evidenced external contract.

Runtime application paths use real collaborators. Test doubles stay in tests. Simulated data and independent simulators stay explicit and prove only their controlled scenario.

Compatibility and migration require an evidenced active input or external consumer. Convert at the owned edge into the current model; avoid parallel sources, dual reads or writes, and silent fallback.

## Apply Proportional Security

Match security work to the confirmed exposure, data sensitivity, trust boundaries, applicable obligations, and controls already in place. Possibility alone does not justify a security feature.

Apply a security improvement inside the current implementation without separate approval only when all of these are true:

- it reuses the existing owner and mechanism;
- it adds no state, dependency, service, job, configuration surface, lifecycle, or operational duty;
- its code and cognitive cost are negligible;
- it preserves the approved behavior and compatibility.

Typical examples are using an existing parameterized API, keeping secrets out of logs, and retaining compatible framework security defaults.

Treat every other security-only addition as a separate feature. Keep it outside the current implementation, finish the requested path, then discuss worthwhile candidates one at a time with the concrete risk, expected benefit, added complexity, ongoing development and operations cost, and the simpler alternative. Implement one only after explicit approval; label it as a proposed security feature rather than an internal detail or settled technical necessity.

Pause the current implementation only when omitting the security feature makes the requested behavior impossible to deliver, violates an explicit contract or applicable obligation, or leaves a known critical exploit on the actual path. State the evidence and smallest sufficient response.

## Match The Effort

- Local copy, style, configuration, deletion, and obvious wiring: make the direct change. Add no abstraction, documentation, or test unless it protects lasting behavior.
- Bounded behavior: use the cheapest focused check that proves the user-visible result or contract.
- Public contracts, cross-module ownership, persistence, or high-impact behavior: trace the boundary and add focused contract or integration coverage.

Tests protect lasting behavior, not source text, file presence, one configuration value, or the fact that an edit happened. Stop when the requested path works. Leave unrelated cleanup and future features alone.
