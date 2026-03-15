#!/usr/bin/env bash
# Pre-push hook: block direct pushes to the develop branch.
# All changes must go through pull requests.

protected_branch="develop"

while read -r _ _ remote_ref _; do
    branch="${remote_ref##refs/heads/}"
    if [ "$branch" = "$protected_branch" ]; then
        echo "🚫 Direct push to '$protected_branch' is not allowed."
        echo "   Create a feature branch and open a pull request instead."
        exit 1
    fi
done

exit 0
