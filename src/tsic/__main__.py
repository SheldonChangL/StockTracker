"""Console entrypoint for the tsic package."""

from tsic import __version__


def main() -> None:
    """Run the tsic CLI entrypoint."""
    print(f"tsic {__version__}")


if __name__ == "__main__":
    main()
