"""Install release dependencies, allowing fresh PyPI releases to propagate."""

import argparse
import subprocess
import sys
import time


def pip_install(arguments, attempts=10, retry_delay=30):
    for attempt in range(1, attempts + 1):
        cache_args = ['--no-cache-dir'] if attempt > 1 else []
        command = [sys.executable, '-m', 'pip', 'install', *cache_args, *arguments]
        result = subprocess.run(command)
        if result.returncode == 0:
            return 0
        if attempt == attempts:
            return result.returncode
        print(f'Dependency installation failed (attempt {attempt}/{attempts}); '
              f'retrying in {retry_delay}s without the pip cache.', flush=True)
        time.sleep(retry_delay)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', action='store_true', help='Include portable build tools')
    args = parser.parse_args(argv)
    extras = 'dev,bundle' if args.bundle else 'dev'
    return pip_install(['-r', 'requirements.txt', f'.[{extras}]'])


if __name__ == '__main__':
    sys.exit(main())
