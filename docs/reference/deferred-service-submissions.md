# Deferred service submissions

An enrolled writable service may opt a new send/reply into `defer_remote`.
KAI does so by default. Authentication and original reply-party checks still
precede enqueue. Host persistence atomically records the immutable envelope
and work fence, returning `state=journaled`, `receipt_stage=host_journaled`,
`hub_acceptance=unconfirmed`. This is not Hub acceptance or recipient delivery.
The caller retains its original submission ID and must not create a new one
when transport fails. Native synchronous calls keep their existing contract.

Only a matching immutable Hub message proves `hub_message_committed` /
`committed`. Remote delivery, presentation and recipient response remain
separate. Commit-to-outbox does not synchronously wait for remote accept.

## Work and revocation

Only explicitly opted-in new submissions enter `submission_work`. Historical
journal rows are never imported or scheduled. A legacy ID without a work row
requires read-only reconciliation, not a resend.

A SQLite compare-and-set changes pending to dispatching before any submission
RPC, so only one worker can attempt it. Current binding/generation, read-only
policy and scope are rechecked; new-send scope is intersected with the original
scope so later grants cannot widen queued new targets. Existing pinned-party
reply authority remains unchanged. Generation changes fence queued work.
Unflagged duplicates cannot bypass an existing deferred work fence.

| State | Automatic dispatch |
| --- | --- |
| pending | One current-policy attempt when due, within deadline |
| dispatching | Only the worker that acquired the durable fence |
| held | None: the prior attempt's outcome may be unknown |
| hub_committed | Existing outbox/delivery lifecycle only |
| blocked | None: policy, identity, conflict or deadline failed |
| cancelled | None: durable tombstone is retained |

Pre-submit metadata failures use bounded backoff. Once submit was attempted,
ambiguous failures are held even when a resolve error appears to suggest no
acceptance. A crash after claiming work is also held on startup. Missing Hub
rows never prove the prior attempt did not commit.

## Public controls

`tproj_reconcile(submission_id)` records only positive immutable Hub proof for
the authenticated sender. It never submits, resumes or releases held work.
`tproj_cancel_submission(submission_id)` can fence only pending work with zero
attempts using the same durable CAS. It does not cancel committed, in-flight,
held or historical work. Both require the existing writable service binding;
arguments cannot select another service or sender. No new grant is introduced.

Exact-ID message/diagnose views preserve receipt boundaries and work metadata.
A transport timeout is not cancellation. Diagnostics keep acceptance unknown,
retain the original ID and classify socket timeouts consistently on Python 3.9
and later. Neither a successful status call nor a healthy process proves that
an earlier message was presented or answered.

## Packaging and operational recovery

The normal unified installer must include `submission_queue.py`; excluding it
would make the next Host startup fail or erase the work-fence implementation.
Adapter runtime/helper and its advertised catalog must be deployed coherently.
The canonical documentation and adapter catalogs describe the same controls.

After any new deferred work exists, blindly reverting to code that ignores the
work table or cancellation tombstones is unsafe. On a regression, pause new
input/dispatch and preserve the journal, status/control code and all fences.
Re-evaluate migration before any old-code recovery. Never restore an old DB or
schedule historical/unknown submissions to test recovery. Preserve unrelated
services, identity, scope, credentials and active native conversations.


Existing Telegram private-v1 and owner-approved group-v2 provenance readers are
packaged as dependencies of the deployed Host/Hub views. Their bindings remain
operator-owned; merely installing these files neither enrolls nor starts a bot,
grants another chat, admits another user, or adds peer-bot fanout. Reply holds,
reserved/unknown outcomes and exact original-chat routing remain durable.
