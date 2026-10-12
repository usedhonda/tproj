# Development change contract

Use this procedure for changes crossing a runtime, identity, configuration, or
deployment boundary. Its purpose is to prevent a locally correct patch from
breaking the running system. It adds no approval, role, or conversation-wide
task gate. Existing authorization and repository completion rules still apply.

## One authoritative specification

Each behavior has one authoritative specification. Identify it and record the
proposed invariant before implementation; update it with the accepted behavior
in the same checkpoint as the code. Link from plans and tests rather than copying
its rules. Label proposals, implemented behavior, and deployed behavior separately.
For messaging and task behavior, use [unified messaging](unified-messaging.md)
and [unified tasks](unified-tasks.md). This document defines the development
procedure, not a second protocol specification.

Use this compact template for the change record. Reference existing guarantees
by section; put enduring behavior changes in the authoritative specification,
not only in a scoped plan:

```text
Intent / authoritative specification:
Observed failure / evidence / hypothesis to falsify:
Before invariant -> after invariant (including behavior that must remain):
Ownership / authenticated identity / identity lifetime:
State transitions / retry identity / terminal and unknown outcomes:
Guarantee boundary: acceptance / processing / delivery (not interchangeable):
Affected source, installed artifacts, services, and configuration consumers:
Dependencies / activation order / supported mixed-version behavior:
Explicitly out of scope:
Acceptance rows: input or event | expected result | direct evidence
Activation / compatible rollback / completion evidence:
```

Identify who owns each transition, which identity survives which lifecycle,
and which authority can change it. An alias, pane label, endpoint, process,
native conversation, and task epoch are not interchangeable identities. Task
ownership does not capture a recipient's independent conversation or ordinary
tools. Preserve existing safety controls without attributing unrelated tools
to whichever task record happens to be present.

Define any at-most-once or exactly-once claim for acceptance, processing, and
delivery separately. A lost response does not prove non-acceptance. Preserve
request IDs across reconnection, consult the recorded result, and leave an
unverifiable outcome unknown instead of repeating a non-idempotent effect.
Keep logical reply identity separate from temporary endpoints. Missing historical
binding evidence may reject an old reply, but must not disable new communication
under a currently authenticated binding.

## Development steps

1. **Fix the boundary before the patch.** Record the user-observed failure as
   fact; distinguish hypotheses. Trace the affected producer, consumer, state
   store, and live configuration authority. Define the invariant and explicit
   exclusions, then start the scoped Task Intent. Do not expand the repair to
   unrelated components.
2. **Select acceptance transitions.** Write only rows that can change the
   implementation or activation decision. The table below is a scenario menu,
   not a mandatory full Cartesian suite. Include affected lifecycle transitions
   rather than proving only a fresh-process happy path.
3. **Implement and stabilize.** Keep code, the authoritative specification, and
   one minimal focused regression together when a protected contract changes.
   Use syntax/static checks and affected existing checks during iteration;
   reuse unchanged green evidence. Do not add a test or review gate per patch.
4. **Activate in dependency order.** Stage compatible backend/schema changes,
   reload the owning services through their supported lifecycle, verify loaded
   capabilities, then activate dependent hosts, hooks, or clients. Disk version
   equality is not capability evidence. Preserve working tools and read-only
   diagnosis when a dependency is old or unavailable; do not bypass identity or
   silently select a legacy mutation path. Record each long-lived consumer that
   must reload, including a client-owned MCP stdio process.
5. **Prove the affected running path and finish.** Distinguish the evidence
   layers below. Run required release/CI gates at the stable checkpoint; reuse
   valid results and rerun only the required scope whose evidence is invalidated
   by relevant changes. Stop checking when scoped acceptance is proved. Complete
   activation, Intent Drift Check, scoped commit, and result report under the
   repository rules. An unactivated artifact is pending, not a completed runtime
   repair. Documentation-only changes need a wording/diff check, not a build.

### Acceptance scenarios

| Input or event, when affected | Expected result to specify |
| --- | --- |
| Delayed message or lifecycle callback | Check current routing, revocation, and lifecycle state without substituting it for historical authorization/native binding proof. Missing past proof holds only that event; valid new communication continues. Preserve exact identity and do not resurrect terminal work. |
| Response lost after a mutation was accepted | Report an unknown outcome; reconciliation or a permitted retry uses the same identity and cannot duplicate the effect. |
| Process/endpoint restart in the same native conversation | Continue only with authenticated historical/current identity evidence; state exactly which access survives. |
| Restart into a different native conversation | Do not inherit historical authority from an alias, pane, or former process. |
| New consumer with old backend, or the reverse | Reject only the unsupported dependent operation before activation; unaffected tools remain usable. |
| Stale claim, epoch, heartbeat, or retired endpoint | Fence stale mutation/delivery using its owning authority; retain authorized diagnosis without fabricating completion. |
| Canonical config changes while a consumer holds an old snapshot | Detect or expose the loaded generation; verify supported reload of the actual consumer before claiming the new value is active. |
| Directory membership changes but a separate policy cache does not | Resolve membership from the stated authority; preserve independent authorization policy rather than silently widening access. |

Replace each selected row with concrete input/state, expected result, and a
bounded observation. “Restart works” or “all tests pass” is not a precise
acceptance condition. Negative cases need only the affected wrong-recipient,
wrong-authority, or wrong-state scenario, not an unlimited route matrix.

## Completion evidence and recovery

Report these layers separately; a lower layer never proves a higher one:

| Layer | Evidence |
| --- | --- |
| Source | Scoped diff, authoritative specification, focused checks at the identified revision. |
| Installed | Distributed artifact identity and installer check; note hosts/components not updated. |
| Loaded | Running process identity, capabilities, and sanitized configuration generation actually consumed; a file write or another process's reload is insufficient. |
| Actual recipient/result | Exact request/message identity and authenticated recipient observation or operation outcome for the affected transition; transport acceptance, health, or listing alone is insufficient. |

Configuration evidence must distinguish the canonical authority, any derived
cache, and each loaded snapshot. Compare the expected revision with the revision
actually loaded by each affected consumer; where no revision exists, use the
corresponding sanitized value or artifact identity and actual behavior. A reload
request alone is not acceptance. Do not reconstruct old claims from current
configuration. Record only non-secret identity/generation
metadata, never credentials or raw configuration containing secrets.

Before activation, state a recovery path compatible with the resulting schema
and durable records. Reverting a binary alone is not safe rollback if the old
reader cannot interpret newly written state. Prefer staged activation or a
documented compatible recovery; preserve unknown operations and diagnostic
access rather than deleting records, detaching ownership, or replaying effects
to make the system appear healthy. Report unresolved evidence as unresolved.
Limit activation, stopping, and recovery to the affected feature and generation.
If written state is not backward-compatible, prefer a scoped forward repair to
an unsafe rollback. This procedure does not authorize additional service stops.

## Incident-to-rule mapping

| Observed failure | Rule derived from the incident |
| --- | --- |
| New task hooks activated before compatible backends blocked ordinary tools. | Probe the loaded dependency chain before activation; preserve unrelated tools and diagnosis. See the task specification's backend compatibility contract. |
| A temporary endpoint pinned a delayed reply and broke same-native continuation. | Specify identity lifetimes and test same-native versus different-native restart; use owner-authenticated continuity, not alias inference. See the messaging continuity contract. |
| Directory registration diverged from a static service address list. | Declare the membership authority and derived consumers; keep discovery distinct from permission policy. |
| Mailbox configuration changed/reloaded while MCP stdio retained an old snapshot. | Enumerate consumers and prove the actual long-lived process loaded the canonical generation. |
| Bounded source tests passed without proving upgrade/restart behavior. | Keep source, installed, loaded, and actual-recipient evidence separate; add only the affected lifecycle acceptance row. |
