import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="digest",
        description="Build the daily digest and send it to the Kindle.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="use a fake LLM instead of the Anthropic API (no paid calls)",
    )
    args = parser.parse_args(argv)

    mode = "fake" if args.fake else "real"
    print(f"digest: running in {mode} mode")
