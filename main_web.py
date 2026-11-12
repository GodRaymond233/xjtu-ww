if __name__ == "__main__":
    from src.identity import apply as apply_identity
    apply_identity()
    from config import config
    from ok import OK

    config = config
    config["gui"] = {
        "type": "web",
        "launch_mode": "pywebview",  # default
    }
    ok = OK(config)
    ok.start()
