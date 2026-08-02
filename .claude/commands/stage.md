Report the current build stage and what is in scope. Argument: `$ARGUMENTS` is an optional stage id (e.g. `S2`) to describe instead of the current one.

1. Read the status table in the `build-stages` skill.
2. Report the current stage, its exit criterion, and how close the repo is to meeting it.
3. List what is explicitly **out** of scope until a later stage.
4. Flag any code already in the repo that belongs to a later stage — building ahead is the failure mode this command exists to catch.

Use the `build-stages` skill. Do not propose work from a later stage without saying so plainly.
