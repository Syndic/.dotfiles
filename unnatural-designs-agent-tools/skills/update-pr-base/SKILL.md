---
name: update-pr-base
description: Bring the current branch up to date by rebasing it onto its PR's base branch (or the repo's default branch, or a base you name) and force-push with lease
argument-hint: "[base branch]"
allowed-tools: Bash(git fetch:*), Bash(git rebase:*), Bash(git push --force-with-lease:*), Bash(git branch:*), Bash(git rev-parse:*), Bash(git rev-list:*), Bash(git symbolic-ref:*), Bash(git status:*), Bash(git log:*), Bash(gh pr view:*), Bash(gh repo view:*)
---

Bring the current branch up to date by rebasing it onto the latest base branch,
then force-push it. Never merge.

1. Pick the base: `$ARGUMENTS` if given; otherwise the current branch's PR base
   (`gh pr view --json baseRefName -q .baseRefName`); otherwise the repo's
   default branch (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`).
   Say which you picked.
2. Confirm the current branch is neither the base nor the repo's default branch.
   If it is, stop and surface that — never rebase/force-push those.
3. `git fetch origin <base>`, and note the old base (`git merge-base HEAD origin/<base>`).
4. `git rebase origin/<base>`. If there are conflicts, stop, report them, and
   wait — do not resolve them without me.
5. Verify the rebased commits are still signed (`git log --show-signature`);
   if any commit lost its signature, stop and surface it before pushing.
6. `git push --force-with-lease`.

Report the old and new base SHAs, and how many commits apart they are.
