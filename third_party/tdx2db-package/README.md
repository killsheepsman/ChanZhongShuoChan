# Bundled tdx2db

This directory contains the upstream distribution of [xbfighting/tdx2db](https://github.com/xbfighting/tdx2db), version 0.5.0. It is bundled so the project installer can resolve the primary local TongDaXin importer even when PyPI access is unreliable.

- Upstream: xbfighting/tdx2db
- Version: 0.5.0
- Package: tdx2db-0.5.0-py3-none-any.whl
- Source snapshot: src/
- License: see src/tdx2db-0.5.0.dist-info/licenses/LICENSE

The application invokes the package without modifying the upstream importer. The generated SQLite database belongs in C:\STOCK\data\chanlun_tdx.db, not in this directory.
