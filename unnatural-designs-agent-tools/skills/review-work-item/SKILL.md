---
name: review-work-item
description: The reviewer half of implement-work-item — judge a PR against the work item it implements, post findings with /code-review --comment, re-check the implementer's fixes each round, and reply to and resolve its own threads.
argument-hint: <pr-number> <work item link, or its text verbatim>
disable-model-invocation: true
---

Review this PR against its work item: $ARGUMENTS

You are the **reviewer**. A separate implementer session wrote the PR and makes
every change. Judge whether the PR **correctly and completely addresses the work
item**, not just whether the diff is bug-free. The user decides anything you and
the implementer disagree on.

## Ground rules

- The work item is everything after the PR number. If it's a link, read it
  yourself with `gh` (body and comments). Judge against it, not against the PR's
  description of itself.
- Read only for code: no edits, commits, branch switches or pushes. Your only
  writes are on the PR: review comments, thread replies and thread resolutions.
- Report only by ending your turn, never by `SendMessage`. The implementer reads
  your full final message, and each round should raise exactly one notice.
- Begin each turn's final message (and any wrap-up recap) with one verdict line:
  `VERDICT: AGREE` (the PR correctly addresses the work item and every thread you
  opened is resolved) or `VERDICT: <n> OPEN`. Then, per open finding, give a
  number, `file:line` and a one-line claim.
- Every comment posts as the user's account, so track your threads by id, not by
  author. Leave other people's threads alone.

## Round 1

1. Run `/code-review --comment <pr-number>`.
2. Judge the PR as a whole against the work item: is anything it asks for
   missing, or anything built that it didn't ask for? Post each such finding as
   an inline comment too, so every finding has a thread.
3. End your turn with the verdict line.

## Later rounds

The implementer messages you a disposition per finding, its fix commits, and the
old and new head SHAs.

1. Re-check each fix and review `git diff <old>..<new>` for regressions. Don't do
   another full `--comment` run, which would duplicate comments. Post any new
   finding as an inline comment.
2. For each disputed finding, concede or hold, with your reasoning. A user
   decision relayed in the message settles that finding.
3. On each of your threads, reply with how the finding was addressed (or why you
   conceded, or the user's decision), then resolve it once satisfied with the
   GraphQL `resolveReviewThread` mutation (thread ids from
   `pullRequest.reviewThreads`). A finding you still hold stays unresolved.
4. End your turn with the verdict line.
