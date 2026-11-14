# Third-party files in this folder

These files are copied, unmodified, from TradingView Lightweight Charts™:

- Source: https://github.com/tradingview/lightweight-charts, release `v5.2.1`
  (annotated tag `bf4bdc64e1ac5d6dc8a1c01e1340cc1cb25ca695`, commit
  `b2ce010e4ad59f6556c9ed60e2b2b30feccdd2d1`, 2026-08-12).
- `lightweight-charts.standalone.production.js`: `dist/` of the npm package
  https://registry.npmjs.org/lightweight-charts/-/lightweight-charts-5.2.1.tgz (tarball sha1
  `5a27ead719573607d4d3483ad2728c055ccea8fd`, the registry's `dist.shasum`); the file's sha256
  is `e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf`. It is the IIFE
  build with its dependency included, which defines `window.LightweightCharts` (README,
  "Build Variants").
- `LICENSE` and `NOTICE`: the repository's own files at that commit (git blobs `174e926` and
  `37971d0`); the package's `LICENSE` is the same file.
- Copyright (c) 2025-2026 TradingView, Inc., as `NOTICE` and the file's header state.
- Licence: Apache License 2.0 (Apache-2.0).

`tests/test_upstream_unmodified.py` checks that these files match upstream byte for byte.
`meridian/strategy_template/chart.py` embeds the `.js` file unchanged in each chart page it
writes under `runs/`.

This notice covers only this folder.
