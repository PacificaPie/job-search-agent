# Integrations

This directory contains source adapters that are candidates for the Campaign discovery layer but
are not yet wired into the production app.

`watchlist_scan.py` is retained from v1 because its Greenhouse/Ashby/Lever JSON access and
deterministic title filtering are useful. It still expects private local `data/watchlist.json` and
an omitted Feishu notification adapter, so it is not part of the verified daily workflow yet.

Before promoting it into `app/`:

1. wrap it as a `JobSource` that returns canonical `JobSnapshot` values;
2. assign results to `global-2027-ai-product`;
3. replace file-based seen/application suppression with the SQLite repositories;
4. add L0 routing cases and L1 source/filter golden cases;
5. keep network fetches read-only and low-frequency.
