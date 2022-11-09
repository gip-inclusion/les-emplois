# Upgrade instructions
## jQuery UI

1. https://www.jsdelivr.com/package/npm/jquery-ui
2. Download and extract the package.
3. Copy the `dist/` directory to `itou/static/vendor/jquery-ui-<VERSION>`.
4. Prune themes directories other than `base`. The following command is probably handy, YMMV:
  ```
  find itou/static/vendor/jquery-ui-*/themes/ -maxdepth 1 -mindepth 1 -not -name base | xargs git rm -ri
  ```
5. Add the remaining files to git.
