import uvicorn
from .api import create_app
from .config import load
from .paths import project_root
from .runtime import Runtime


def main():
    root = project_root()
    config = load(root)
    runtime = Runtime(config, root)
    runtime.start()
    try:
        uvicorn.run(create_app(runtime, root / "web" / "dist"), host=config.host, port=config.port)
    finally:
        runtime.stop()


if __name__ == "__main__":
    main()
