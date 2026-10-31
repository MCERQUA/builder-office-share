# Sound sources

One row per audio file under `sounds/`. The commit check reads this table:

- `file` is the path under `sounds/` (for example `clips/air_horn.mp3`).
- `source` is a link to where the clip came from, or "made by <who>".
- `license` is the license it was shared under (CC0, CC-BY 4.0, ...). If it's CC-BY, say who to credit.

A row whose source or license is blank, `unknown`, `?`, `todo` or `tbd` doesn't count, and the clip
won't commit.

| file | what it is | source | license | added by |
|---|---|---|---|---|
