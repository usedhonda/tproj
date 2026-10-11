# Native inbox notice contract

The unified host exposes `inbox_notice` as a bounded, authenticated read for
native `PostToolUse` safe points. It returns at most three message IDs and the
canonical sender address, never a body. The operation does not claim, consume,
present, acknowledge, resend, or otherwise modify messages.

The hook helper authenticates through the local host caller binding and passes
native conversation context when supplied by the tool event. It has a sub-one
second timeout and fails open. Persistent deduplication is local to the native
conversation (or the authenticated CLI endpoint when no native ID exists) and
the exact message ID, so an active recipient can read the original message by
ID without a forced prompt or proxy relay.
