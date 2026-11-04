# Working together in this repo

Multiple agents (Jambot, Quinn, gpu-claude, Colossus, mac-claude, and whoever else gets added)
read and write this repo. These rules exist so two agents working at once don't clobber each
other's in-progress work or fight over the same files.

## 1. Always branch. Never commit straight to `main`.

Before touching anything, create a branch named `<your-short-name>/<task-slug>`:

```
git checkout main && git pull
git checkout -b gpu-claude/sound-clips-batch3
```

Examples: `quinn/manifesto-draft`, `mac-claude/discord-workflow-doc`, `colossus/benchmark-notes`.
One branch per task, not one long-lived branch per agent — a stale branch sitting open for days
is how merges get painful. Short-lived and specific beats broad and long-lived.

## 2. Sharing ONE machine's checkout? Use a worktree per branch, not one shared working copy.

If more than one agent writes from the same box (some machines host more than one agent's
work), don't all `git checkout` back and forth in the same directory — that
stomps on whichever agent's uncommitted files are sitting there. Instead, each active branch
gets its own worktree, sharing the one `.git`:

```
git worktree add ../builder-office-share-quinn quinn/manifesto-draft
git worktree add ../builder-office-share-gpu-claude gpu-claude/sound-clips-batch3
```

Each worktree is a real directory with its own checked-out files; commits from any of them go
into the same repo history. Remove a worktree when its branch is merged:
`git worktree remove ../builder-office-share-quinn`.

A single agent working alone on one task at a time doesn't need this — plain `git checkout -b`
in the one clone is fine. Worktrees are for when two agents would otherwise want the SAME
directory checked out to two different branches at once.

## 3. Stay in your own folder when you can.

Even with branches, two agents editing the SAME file around the same time means a merge
conflict either way. Where the content allows it, work in your own namespace:

- `sounds/<your-name>/`, `notes/<your-name>/` for anything that's naturally yours.
- Shared files (`README.md`, `sounds/SOURCES.md`, this file) still get edited by anyone — just
  `git pull --rebase` right before you touch them, so your branch starts from the latest version
  instead of an old one.

## 4. Before you push: were you actually told to put this here?

Hard rule (see README's "No raw transcripts, ever"): never commit a raw transcript, chat log, or
anything nobody asked you to add. Every commit should trace back to something Mike instructed,
or a task that an instructed task clearly implies. If you can't point to the instruction, don't
push it -- ask in mesh instead of guessing that it's wanted here.

## 5. Push, let the check run, then merge.

```
git push -u origin <your-branch>
```

GitHub runs the same public-content check (`check.yml`) on every push and pull request — wait
for it to go green before merging.

- **Routine, low-stakes additions** (a sound clip, a local-model note, a bot-to-bot note): once
  the check is green, fast-forward merge your own branch into `main` yourself and delete the
  branch. No review needed for this class of content.
- **Anything that feels like a judgment call** (new rules in this file or the README, a
  structural change, content you're not sure is public-safe even after the check passes): open a
  pull request instead of merging it yourself, and say so in mesh so host or Mike can look at it
  before it lands.
- Never `--no-verify`, never force-push `main`.

## 6. If you find a stale branch or worktree

A branch whose task is done and merged: delete it (`git push origin --delete <branch>` plus
`git branch -d <branch>` locally). A worktree nobody's using: `git worktree remove`. Don't delete
another agent's branch that still looks active — ask in mesh first if you're not sure.
