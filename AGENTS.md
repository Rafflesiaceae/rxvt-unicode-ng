- Ignore all files below `./.legacy/` for changes - they are historic.

- Don't touch any directory below `./vendor/*` - they are upstream-managed.

- New source code files must have the `_neo` filename suffix.

- Minimize Merge Conflicts:
    - Changes to this repository should be done to minimize conflicts as upstream
      changes are integrated into this repository all the time.

    - Substantial changes to upstream source files are best split into new
      separate files, with suffixed '_neo' filenames.

    - Before proposing refactors, cleanup, removals, inspect active dependencies
      and the integration changes they require. Assess the complete resulting
      diff against the goal of minimizing upstream merge conflicts.
      Disabled-by-default code is not necessarily unused, and cleaner file
      organization alone does not justify increasing divergence from upstream.

    - Moving files is general fine.
