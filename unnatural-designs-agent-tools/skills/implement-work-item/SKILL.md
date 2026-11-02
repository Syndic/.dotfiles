---
name: implement-work-item
description: Implement a triaged work item end to end — surface ambiguity before coding, ship it as a PR, then iterate with a separate review session running /code-review --comment until both sessions agree, escalating disagreements to the user, and finish with a per-file summary to guide the merge review.
argument-hint: <issue number or URL, or a description of the work>
disable-model-invocation: true
---

Implement this work item: $ARGUMENTS

You are the **implementer**. A separate **reviewer** session checks your PR. You
and the reviewer iterate until you both agree the PR correctly addresses the work
item; the user decides anything you two disagree on.

## 1. Understand the work before touching code

1. If the argument names an issue or PR, read it in full with `gh` (body and
   comments). Read the code it touches.
2. State, briefly: what you'll change, where, how you'll test it, and what's out
   of scope.
3. List every ambiguity that would change *what* gets built — conflicting
   requirements, an unstated choice between designs, unclear scope, an acceptance
   criterion you can't check. Answer the ones the code or repo docs settle
   yourself; don't ask about those.
4. If any remain, **stop and ask** — end the turn with the questions and implement
   nothing. If none remain, say so in one line and continue.

## 2. Implement and open the PR

1. Never work on the default branch. If you're on it, create a feature branch
   first.
2. Implement, including the docs and tests the change needs. Validate with the
   project's own checks (tests, linters) and fix what fails.
3. Commit (signed, per the repo's rules), push, and open a PR whose body links the
   work item and says how it was validated. Note the PR number.

## 3. Start the reviewer

Start one session with `mcp__ccd_session__start_session` (load it with
`ToolSearch` if it's deferred): `initiation: "user_asked"` (this command is the
user's request for it), `context: "fresh"`, `use_worktree: false` (it only
reads), `name: "review-pr-<number>"`. If session tools aren't available here
(for example in the CLI), stop and tell the user, and ask whether to run the
review in a subagent instead.

The brief tells the reviewer:

- The work item (link or full text) and the PR number. Its job is to judge
  whether the PR **correctly and completely addresses that work item**, not just
  whether the diff is bug-free.
- Run `/code-review --comment <number>`.
- Read only: no edits, commits, branch switches or pushes. The implementer makes
  every change.
- Begin each turn's final message with one verdict line: `VERDICT: AGREE` (the PR
  correctly addresses the work item and nothing is outstanding) or
  `VERDICT: <n> OPEN` — then, per open finding, a number, `file:line`, and a
  one-line claim. The implementer sees only the first ~400 characters when the
  turn ends, so the verdict line must come first.
- On later rounds the implementer will message it with a disposition per finding
  and the new commits. Re-check each fix, review the new commits for regressions
  (`git diff <old-head>..<new-head>`, not a repeat full-PR `--comment` run, which
  would duplicate comments), and say for each disputed finding whether it concedes
  or still holds — with its reasoning. Reply by `SendMessage` to the message's
  `from`, then end the turn with the verdict line.

Then end your turn. The app continues you when the reviewer finishes; don't poll.

## 4. Iterate to agreement

For each round:

1. Read the reviewer's findings — its message, plus the PR's review comments
   (`gh api repos/{owner}/{repo}/pulls/<number>/comments`) on round 1.
2. Decide each finding on its merits, never by deference:
   - **Accept** — fix it (new commit, never an amend), validate, push.
   - **Dispute** — explain concretely why it's wrong or out of scope.
3. `SendMessage` the reviewer (its `local_…` id) with every finding's disposition,
   the fix commits, and the old and new head SHAs. End your turn.

**Escalate to the user** — stop iterating, present both positions side by side
with each session's reasoning, and wait — when:

- a finding you disputed is still held by the reviewer after its reply (you
  disagree on *whether* to address it), or
- you agree it needs addressing but disagree on *how*, or
- three rounds pass without `VERDICT: AGREE` (the loop isn't converging).

Relay the user's decision to the reviewer quoting their words, then continue.

## 5. Hand off for the merge review

When the reviewer's verdict is `VERDICT: AGREE` and you have nothing outstanding:

1. Confirm the branch is pushed and the PR head matches your local head.
2. Summarize, for the user's review before merging:
   - **Per file** (from `git diff --stat origin/<default>...HEAD`): what changed and
     why, grouped by purpose when several files serve one change. Point at the
     parts most worth a careful look.
   - **Review outcome**: each finding, and whether it was fixed (commit) or
     dropped (why, and who decided).
   - **Not verified**: anything no check covered.
3. Offer to archive the reviewer session; archive it only on the user's yes.
