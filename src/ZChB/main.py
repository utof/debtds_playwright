# Thin entrypoint redirecting to src.runner per your structure decision.
from .runner import run

if __name__ == "__main__":
    run()
