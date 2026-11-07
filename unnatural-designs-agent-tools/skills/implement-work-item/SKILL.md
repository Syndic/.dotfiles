---
name: implement-work-item
description: Implement a triaged work item end to end — surface ambiguity before coding, ship it as a PR, then iterate with a separate review session (review-work-item) until both sessions agree, escalating disagreements to the user, and notify the user with a per-file summary once they agree, fixing CI failures the PR causes and surfacing unrelated ones. Never merges; the user does.
argument-hint: <issue number or URL, or a description of the work>
disable-model-invocation: true
---

Implement this work item: $ARGUMENTS

You are the **implementer**. A separate **reviewer** session checks your PR. You
and the reviewer iterate until you both agree the PR correctly addresses the work
item; the user decides anything you two disagree on.

Never merge the PR, enable auto-merge, or offer to merge it. The user does a
final review and merges it themself.

Before step 2's PR, load the deferred tools this uses with one `ToolSearch`:
`mcp__ccd_pr__set_monitor`, `mcp__ccd_session__start_session`, `mcp__ccd_session_mgmt__list_events` and
`PushNotification`. If session tools aren't available here (for example in the
CLI), stop and tell the user before step 3, and ask whether to run the review in
a subagent instead.

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
   nothing. The user's answers become part of the work item. If none remain, say
   so in one line and continue.

## 2. Implement and open the PR

1. Never work on the default branch. If you're on it, create a feature branch
   with a name you choose and say which; invoking this command is the go-ahead,
   so don't stop to ask.
2. Implement, including the docs and tests the change needs. Validate with the
   project's own checks (tests, linters) and fix what fails.
3. Commit (signed, per the repo's rules), push, and open a PR whose body links the
   work item and says how it was validated. Note the PR number.
4. Turn on the app's CI monitor so failures wake you: `mcp__ccd_pr__set_monitor`
   with `auto_fix: true` and the PR's URL. If the call is denied, tell the user in
   one line that CI failures won't wake you until they turn on Auto-fix in the PR
   bar or allow the call, and carry on.

## 3. Start the reviewer

Call `start_session` with `initiation: "user_asked"` (this command is the user's
request for it), `context: "fresh"`, `use_worktree: false` (it only reads code),
`name: "review-pr-<number>"`, a `title`, and:

- `prompt`: `/unnatural-designs-agent-tools:review-work-item <number> <work item>`.
  The work item is the link the user gave, or their text verbatim, plus every
  answer or decision the user has given about the work so far, verbatim. Never your paraphrase, plan or summary: the reviewer
  exists to catch a misreading, and your words would carry it over.
- `background` (80+ characters): the repo's conventions, and that the user
  decides disagreements. Leave out the work and your approach.

Then end your turn. The app continues you when the reviewer finishes or CI fails;
don't poll. If the app stops continuing you (it holds notes after many in a row),
the loop resumes from the held note on the user's next message.

## 4. Iterate to agreement

Each time you're continued, handle what woke you, then check step 5's condition:

- **The reviewer's turn ended.**
  1. Read its full final message with `list_events` (the notice quotes only the
     first ~400 characters). On round 1, also read its review comments
     (`gh api repos/{owner}/{repo}/pulls/<number>/comments`).
  2. Decide each finding on its merits, never by deference: **accept** (fix it in
     a new commit, never an amend, then validate and push) or **dispute** (explain
     concretely why it's wrong or out of scope).
  3. Reply on each of the reviewer's threads with its disposition (the fix commit,
     or why it was dropped). The reviewer resolves threads, not you.
  4. `SendMessage` the reviewer (its `local_…` id) every disposition, the fix
     commits, and the old and new head SHAs.
- **CI failed** on the latest commit. Read the failing logs and decide whether
  this PR caused it.
  - **Unrelated**: the same check also fails on the default branch's latest
    commit, or the logs point at something the PR doesn't touch. Don't fix it in
    this PR; surface it to the user with that evidence (in step 5's summary, or
    a brief `PushNotification` and message if you've already notified).
  - **Caused by the PR**: fix (new commit), validate, push, and send the fix to
    the reviewer as a round.
- **A merge conflict.** Bring the branch up to date only by rebasing, never by
  merging (so not `mcp__ccd_host__sync_with_base_branch`, which merges): fetch,
  `git rebase origin/<default>`, resolve, check every commit is still signed,
  validate, and `git push --force-with-lease`. Send it to the reviewer as a
  round, saying it was a rebase and giving the old and new base SHAs.
- **A review comment the reviewer posted mid-round.** Ignore it and wait for its
  verdict.
- **A message from the user.** Act on it, and relay any decision or new
  requirement in it to the reviewer quoting their words, so the reviewer doesn't
  flag it as a misreading.

**Escalate to the user** — stop iterating, present both positions side by side
with each session's reasoning, and wait — when:

- a finding you disputed is still held by the reviewer after its reply (you
  disagree on *whether* to address it), or
- you agree it needs addressing but disagree on *how*, or
- the reviewer returns `VERDICT: <n> OPEN` three rounds in a row (a round is
  your dispositions going out and its verdict coming back) with no message from
  the user in between (the loop isn't converging).

Relay the user's decision to the reviewer as above, then continue.

## 5. Notify the user

Notify the user as soon as all of these hold:

- the reviewer's latest verdict is `VERDICT: AGREE` and you have nothing
  outstanding;
- the branch is pushed, with the PR head at your local head; and
- no required check on the PR head is failing because of this PR
  (`gh pr checks <number> --required`). Don't wait on pending checks (the app
  doesn't wake you when CI passes), non-required checks, or failures you judged
  unrelated in step 4; name them in the summary.

To notify, send a one-line `PushNotification`, then end your turn with this
summary for the user's review before merging:

- **Per file** (from `git diff --stat origin/<default>...HEAD`): what changed and
  why, grouped by purpose when several files serve one change. Point at the parts
  most worth a careful look.
- **Review outcome**: each finding, and whether it was fixed (commit) or dropped
  (why, and who decided). Name any unresolved thread that isn't the reviewer's.
- **CI** on the PR head: required checks passed or still running; any
  non-required failure (and whether you're fixing it); any unrelated failure,
  with the evidence.
- **Not verified**: anything no check covered.

## 6. After notifying

A CI failure on the PR head still wakes you (step 2's monitor). Decide as in
step 4 whether the PR caused it. If it's unrelated, surface it as step 4 says.
If the PR caused it, send a brief `PushNotification` and message saying you have
work left, with a concise summary of what failed, fix it as in step 4, and
notify again with a short update once step 5's conditions hold for the new head.

Leave the reviewer session running, since a CI fix needs its review; the user
archives it.
