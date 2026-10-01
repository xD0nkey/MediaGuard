import logging
import uvicorn
from .api import create_app
from .config import load
from .paths import project_root
from .runtime import Runtime


LOG_FORMAT = "[%(asctime)s.%(msecs)03d] [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging():
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT, force=True)


def main():
    configure_logging()
    root = project_root()
    config = load(root)
    runtime = Runtime(config, root)
    runtime.start()
    try:
        uvicorn.run(create_app(runtime, root / "web" / "dist"), host=config.host, port=config.port,
                    log_config=None)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
