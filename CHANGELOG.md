# Changes

## 4.0.1 — geometry correction

- Define slab layers by projection onto the surface normal, then rotate the
  exported surface plane into xy and apply the requested vacuum on each side.
- Trim interface substrate and film to the requested number of atomic planes
  adjacent to the interface, preserving the requested initial gap and 15 A
  external vacuum. Previously, (100) Al interfaces could contain twice the
  requested atomic planes because the underlying library uses unit planes.
- Add coordinate-based regression coverage for 27 slab and 18 interface cases.
  The Windows baseline remains recorded; two deliberate geometry corrections
  are explicitly fingerprinted rather than described as unchanged algorithms.
- Keep existing controls, presets, workflow stages and feature scope.

## 4.0.0 — 2026-09-28

- Restore the complete original Windows desktop application on Linux:
  structure viewer/editor, surface/interface modeling, independent layer and
  separation controls, inputs, dependent workflows, task center, remote files,
  results, post-processing and controlled AI assistant.
- Preserve every original calculation template, scientific implementation,
  queue control and Agent tool. Remove the 3.x terminal edition from the current
  source tree; historical versions remain in Git tags and releases.
- Adapt display text, fonts, scrolling, packaging, file/editor/terminal opening,
  user-data paths and secure credential storage for Linux.
- Include the original regression tests plus focused platform/translation
  contract checks and headless Linux acceptance.

This release supersedes 3.1.0 and 3.0.1. Manuscript work is outside its scope.
