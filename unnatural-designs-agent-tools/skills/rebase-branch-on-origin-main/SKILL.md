---
name: rebase-branch-on-origin-main
description: Bring the current branch up to date with origin/main and force-push with lease
allowed-tools: Bash(git fetch:*), Bash(git rebase:*), Bash(git push --force-with-lease:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git symbolic-ref:*), Bash(git status:*), Bash(git log:*)
---

Bring the current branch up to date by rebasing it onto the latest
`origin/main`, then force-push it.

1. Confirm the current branch is NOT the default branch (main/master/develop).
   If it is, stop and surface that — never rebase/force-push the default branch.
2. `git fetch origin main`.
3. `git rebase origin/main`. If there are conflicts, stop, report them, and
   wait — do not resolve them without me.
4. Verify the rebased commits are still signed (`git log --show-signature`);
   if any commit lost its signature, stop and surface it before pushing.
5. `git push --force-with-lease`.

Report how many commits the new base is from the previous base commit.
