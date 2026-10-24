- Ignore all files below ./.legacy/ for changes.

- Minimize Merge Conflicts:
    - Changes to this repository should be done to minimize conflicts as upstream
      changes are integrated into this repository all the time.

    - Substantial changes to upstream files are best split into new separate
      files, with suffixed '_neo' filenames.

    - Before proposing refactors, cleanup, removals, or file moves, inspect active
      dependencies and the integration changes they require. Assess the complete
      resulting diff against the goal of minimizing upstream merge conflicts.
      Disabled-by-default code is not necessarily unused, and cleaner file
      organization alone does not justify increasing divergence from upstream.
