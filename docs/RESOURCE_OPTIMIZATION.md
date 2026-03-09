# Resource Optimization

## Pipeline

1. Audit lazy-loading hints in QML:

```bash
python tools/audit_lazy_loading.py --qml-dir qml/DropMeQML --report docs/LAZY_LOADING_AUDIT.md
```

2. Optimize image assets:

```bash
python tools/optimize_assets.py --input images --output images-optimized
```

Or in-place:

```bash
python tools/optimize_assets.py --input images --in-place
```

## Current changes applied

- Added explicit `asynchronous: true` and `cache: true` in:
  - `qml/DropMeQML/Resource.qml`
  - `qml/DropMeQML/MultilingualResource.qml`

- Generated lazy-loading audit report:
  - `docs/LAZY_LOADING_AUDIT.md`

## Notes

- Asset optimization script requires Pillow.
- Integration with build/release can call `tools/optimize_assets.py` as a pre-package step.
