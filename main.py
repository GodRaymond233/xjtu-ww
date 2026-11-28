if __name__ == '__main__':
    import multiprocessing
    import os
    import sys
    from pathlib import Path

    multiprocessing.freeze_support()
    if getattr(sys, 'frozen', False):
        os.chdir(Path(sys.executable).resolve().parent)
    from src.windows_runtime import ensure_admin
    if getattr(sys, 'frozen', False):
        try:
            ensure_admin()
        except OSError as error:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'无法以管理员身份启动 XJTU-WW。请检查兼容性设置后重试。\n'
                                             f'Administrator startup failed. Check compatibility settings.\n{error}',
                                             'XJTU-WW', 0x10)
            sys.exit(1)
    if '--apply-update' in sys.argv or '--recover-update' in sys.argv:
        from src.portable_update import installer_main
        sys.exit(installer_main())
    if getattr(sys, 'frozen', False):
        from src.portable_update import guard_pending_update, parse_post_update_arg
        post_update = parse_post_update_arg(sys.argv)
        try:
            guard_pending_update(Path.cwd(), post_update)
        except OSError as error:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'XJTU-WW', 0x10)
            sys.exit(1)
    from src.telemetry import has_prior_configs
    prior_configs = has_prior_configs(Path.cwd())
    from src.identity import apply as apply_identity
    apply_identity()
    from config import config
    from ok import OK

    if getattr(sys, 'frozen', False):
        config['version'] = Path('version.txt').read_text(encoding='utf-8').strip()
    config['_had_prior_configs'] = prior_configs
    ok = OK(config)
    ok.start()
