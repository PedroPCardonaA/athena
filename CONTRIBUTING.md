# Contributing

The project values **simplicity, efficiency and security**. Keep it small: server-rendered pages, SQLite, few dependencies.

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest httpx
make test
make dev        # build from source and run on 127.0.0.1:8787
```

- Add a test for new behaviour (`tests/`). Schema changes go in a new entry at the end of `db.MIGRATIONS` plus a migration test; never edit an existing entry.
- No inline scripts/styles (the CSP forbids them) and no new JS build step.
- Open an issue before large features. By contributing you agree your work is released under the MIT license.

## Pull request workflow
- `master` is protected: changes land through a pull request from a fork or branch, with the `test` check passing and one approving review (the maintainer can merge their own PRs).
- Keep PRs focused; describe what and why, and fill in the checklist.
- Be kind: see the [Code of Conduct](CODE_OF_CONDUCT.md). Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).

