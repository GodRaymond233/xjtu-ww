if __name__ == '__main__':
    import multiprocessing
    import os
    import sys
    from pathlib import Path

    multiprocessing.freeze_support()
    if getattr(sys, 'frozen', False):
        os.chdir(Path(sys.executable).resolve().parent)

    from config import config
    from ok import OK

    if getattr(sys, 'frozen', False):
        config['version'] = Path('version.txt').read_text(encoding='utf-8').strip()
    ok = OK(config)
    ok.start()
