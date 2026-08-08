import contextlib
import io
import os
import sys

from kpin import cli


def run_cli(args, cwd=None, input=None):
    """Run the CLI in-process, capturing stdout/stderr.

    Returns a dict with rc, out, err. KpinError is caught and converted to
    exit code 1 with the message on stderr, mirroring main(). argparse usage
    errors (SystemExit 2) are captured as rc=2 with the message on stderr.
    """
    out_buf = io.StringIO()
    err_buf = io.StringIO()

    try:
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            parsed = cli.build_parser().parse_args(args)
    except SystemExit as exc:
        return {
            "rc": exc.code or 0,
            "out": out_buf.getvalue(),
            "err": err_buf.getvalue(),
        }

    if cwd:
        old = os.getcwd()
        os.chdir(cwd)
    else:
        old = None
    old_stdin = sys.stdin
    if input is not None:
        sys.stdin = io.StringIO(input)

    rc = 0
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        try:
            rc = cli.dispatch(parsed)
        except cli.KpinError as exc:
            err_buf.write(f"kpin: {exc}\n")
            rc = 1

    if old:
        os.chdir(old)
    sys.stdin = old_stdin
    return {"rc": rc, "out": out_buf.getvalue(), "err": err_buf.getvalue()}
