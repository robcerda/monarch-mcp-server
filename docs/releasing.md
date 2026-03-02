# Releasing

This document covers the release process for the Monarch MCP Server package.

## Version Scheme

Versions follow [PEP 440](https://peps.python.org/pep-0440/) and are derived automatically from git tags via [setuptools-scm](https://setuptools-scm.readthedocs.io/). No version numbers are hardcoded in source files.

| Stage | Tag pattern | Example | Purpose |
|---|---|---|---|
| Dev | `vX.Y.Z.devN` | `v1.0.0.dev1` | Early development builds |
| Alpha | `vX.Y.ZaN` | `v1.0.0a1` | Feature-incomplete previews |
| Beta | `vX.Y.ZbN` | `v1.0.0b1` | Feature-complete, testing |
| Release candidate | `vX.Y.ZrcN` | `v1.0.0rc1` | Final validation before stable |
| Stable | `vX.Y.Z` | `v1.0.0` | Production release |

## Publish Routing

The CI pipeline automatically routes packages based on the tag:

| Tag type | On tag push (automatic) | Manual dispatch |
|----------|------------------------|-----------------|
| **Prod** (`v1.0.0`) | CI → Build → GitHub Release → PyPI → MCP Registry | N/A |
| **RC** (`v1.0.0rc1`) | CI → Build → GitHub Release only | Choose: PyPI, MCP Registry, or both |
| **Prerelease** (`v1.0.0.dev1`) | CI → Build → TestPyPI → GitHub Release | N/A |

This lets contributors test pre-release packages from TestPyPI without polluting the production PyPI index. RC publishing to PyPI and MCP Registry is manual, giving maintainers control over when an RC is promoted to those registries.

## Workflow Chart

Build and MCPB bundle steps are shared via reusable workflows (`build.yml`, `build-mcpb.yml`). PyPI publish steps are inlined because OIDC trusted publishing does not work with reusable workflows.

```
Tag push (v*)
  │
  ├─ CI (lint + test)
  │   │
  │   └─ Build ·················· (reusable: build.yml)
  │       │
  │       ├─ Detect release type
  │       │   │
  │       │   ├─ prod ──────► PyPI ──► MCP Registry
  │       │   │
  │       │   ├─ rc ────────► (skip — publish manually later)
  │       │   │
  │       │   └─ prerelease ► TestPyPI
  │       │
  │       └─ Build mcpb ········· (reusable: build-mcpb.yml)
  │           └─► GitHub Release
  │
  │
Manual dispatch (RC only)
  │
  ├─ Validate tag
  │   │
  │   ├─ Build ·················· (reusable: build.yml)
  │   │
  │   ├─ Build mcpb (if needed) · (reusable: build-mcpb.yml)
  │   │
  │   └─ target?
  │       │
  │       ├─ pypi ──────────► PyPI
  │       │
  │       ├─ mcp-registry ──► MCP Registry
  │       │
  │       └─ both ──────────► PyPI ──► MCP Registry
```

## How to Release

### Production Release

1. **Ensure `main` is up to date** with all changes you want to release.

2. **Create and push a tag**:
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```

3. **CI runs automatically**:
   - Pylint and pytest must pass (CI gate)
   - Package is built (sdist + wheel)
   - Package is published to PyPI via OIDC trusted publishing
   - Package is published to MCP Registry

4. **GitHub Release is created** with the `.mcpb` bundle attached.

### Pre-release (dev, alpha, beta)

1. **Create and push a tag**:
   ```bash
   git tag v1.0.0b1
   git push origin v1.0.0b1
   ```

2. **CI runs automatically** and publishes to TestPyPI.

3. **GitHub Release is created** and marked as a pre-release.

### Release Candidate (RC)

1. **Create and push a tag**:
   ```bash
   git tag v1.0.0rc1
   git push origin v1.0.0rc1
   ```

2. **CI runs automatically** — only a GitHub Release is created (marked as pre-release). No packages are published yet.

3. **Manually publish** when ready, via GitHub Actions UI or CLI:
   ```bash
   # Publish to PyPI only
   gh workflow run publish-rc.yml -f tag=v1.0.0rc1 -f target=pypi

   # Publish to MCP Registry only
   gh workflow run publish-rc.yml -f tag=v1.0.0rc1 -f target=mcp-registry

   # Publish to both
   gh workflow run publish-rc.yml -f tag=v1.0.0rc1 -f target=both
   ```

   Or use the GitHub UI: **Actions → Publish RC → Run workflow**.

## Installing Pre-release Versions

To install a pre-release version from TestPyPI for testing:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ monarch-mcp
```

The `--extra-index-url` flag ensures dependencies are still resolved from PyPI.

## CI Gate

Every publish (TestPyPI or PyPI) requires the CI workflow to pass first. This includes:

- `pylint` scoring 10.00/10
- `pytest` with 90%+ coverage

The publish workflow reuses `ci.yml`, `build.yml`, and `build-mcpb.yml` via `workflow_call`.

## MCP Bundle

The `.mcpb` bundle is built for every tagged version and attached to the GitHub Release. Pre-release tags (dev, alpha, beta, RC) are automatically flagged as pre-releases on GitHub.
