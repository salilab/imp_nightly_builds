This is a simple [Flask](https://palletsprojects.com/p/flask/) application
to show the [IMP](https://integrativemodeling.org/) nightly build results
page at https://integrativemodeling.org/nightly/results/.

## Configuration

1. Create a file `Makefile.include` in the same directory as `Makefile` that
   sets the `WEBTOP` variable to a directory readable by Apache.

2. Create a configuration file `<WEBTOP>/instance/imp-results.cfg`. This should
   be readable only by Apache (since it contains passwords) and contain
   a number of key=value pairs:
   - `HOST`, `DATABASE`, `USER`, `PASSWORD`: parameters to connect to the
     MySQL server.
   - `TOPDIR`, `LAB_ONLY_TOPDIR`: directories where IMP build results (both
     public and lab-only) can be found.
   - `MAIL_SERVER`, `MAIL_PORT`, `ADMINS`: host and port to connect to to
     send emails when the application encounters an error, and a Python
     list of users to notify.

## Apache setup

1. Install `mod_wsgi`.
2. Add `Alias` rule to the Apache configuration to point
   `/nightly/results/static` to `<WEBTOP>/static`.
3. Add a suitable `WSGIScriptAlias` rule to the Apache configuration pointing
   `/nightly/results/` to `<WEBTOP>/results.wsgi`.

## Deployment

Use `make test` to test changes to the application, and `make install` to
deploy it (this will install the files to the `WEBTOP` directory).
