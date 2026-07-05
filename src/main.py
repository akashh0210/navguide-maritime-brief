import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("NavGuide Weekly Maritime Intelligence Brief - pipeline starting")
    # Phases 1-4 will be wired in here as each phase is verified and merged


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log.exception("Pipeline failed: %s", exc)
        sys.exit(1)
