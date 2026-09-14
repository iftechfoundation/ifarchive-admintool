# Admin tool JSON API

Bulk volunteer operations: upload into `/incoming`, move files, and update Index entries. Rebuild indexes once at the end via the HTML UI (there is no rebuild API).

## Authentication

Every request is a **POST** with form fields:

- `user` — admin username (or email)
- `password` — password

The HTML login session cookie does **not** authenticate the API. HTTP Basic is not used. Credentials must be sent on every request.

Responses are `application/json`. Errors look like `{"error":"…"}` with an appropriate HTTP status.

## Path conventions

Paths in `from` / `to` are relative labels:

- `incoming/<file>`
- `trash/<file>`
- `<archive-dir>/<file>` (optional `if-archive/` prefix; leading `/` ignored)

Examples: `incoming/game.zip`, `unprocessed/game.zip`, `games/zcode/game.zip`.

Move may also rename: the basename in `to` can differ from `from`. Conflicts return **409 Conflict**. Path traversal and non-Archive directories return **400**.

## `POST /api/upload`

Multipart form: `user`, `password`, `file`, `rights`, optional `filename` (override basename).

`rights` must be `author` or `tried` (same values as the public upload form):

- `author` — “I am the author of this file and I give permission”
- `tried` — “to the best of my knowledge the author is okay with this”

```bash
curl -F user=alice -F password=secret -F rights=tried -F file=@game.zip \
  https://admin.ifarchive.org/admin/api/upload
```

Success:

```json
{"filename": "game.zip", "md5": "…"}
```

If a file with that name already exists in `/incoming`, the file is stored as `name.1`, `name.2`, … (never overwritten), so you'll need to read the `filename` from this API to move the file you uploaded to its intended location.

## `POST /api/move`

Form fields: `user`, `password`, `from`, `to`.

```bash
curl -F user=alice -F password=secret \
  -F from=incoming/game.zip -F to=unprocessed/game.zip \
  https://admin.ifarchive.org/admin/api/move

curl -F user=alice -F password=secret \
  -F from=unprocessed/game.zip -F to=games/zcode/game.zip \
  https://admin.ifarchive.org/admin/api/move
```

Success:

```json
{"from": "incoming/game.zip", "to": "unprocessed/game.zip"}
```

When moving between archive directories (not into `unprocessed`), an Index entry is moved with the file when present (including under the new name if renaming).

## `POST /api/index`

Form fields: `user`, `password`, `dirname`, `filename`, and at least one of `description` / `metadata`.

- `dirname` — archive-relative directory (`games/zcode`, or empty for the archive root)
- `filename` — file basename, or `.` for the directory’s own Index block
- Omitted `description` or `metadata` leaves that field unchanged; an empty value clears it
- `metadata` is a Markdown-style meta block (`key: value` lines)

```bash
curl -F user=alice -F password=secret \
  -F dirname=games/zcode -F filename=game.zip \
  -F description='A fine game.' \
  -F metadata=$'tuid: 0123456789abcdef\n' \
  https://admin.ifarchive.org/admin/api/index
```

Success returns the stored entry:

```json
{"dirname": "games/zcode", "filename": "game.zip", "description": "…", "metadata": "…"}
```
