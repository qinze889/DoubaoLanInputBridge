"""Keep failed compatibility checks visible in CI annotations as well as logs."""
import subprocess
import sys


def escaped(value):
    return value.replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')


def main(args):
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
    print(result.stdout, end='', flush=True)
    if result.returncode:
        lines = result.stdout.splitlines()
        failures = [line for line in lines if line.startswith(('FAILED ', 'ERROR ', 'E   ', 'error[', 'error:'))]
        detail = '\n'.join(failures[-16:] or lines[-24:])[-5000:]
        print('::error title=Compatibility check failed::'+escaped(detail or 'Check exited without output'))
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
