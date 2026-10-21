"""FORGE — your voice, your model. Entry point."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from forge.app import build_app


def main():
    p = argparse.ArgumentParser(description="FORGE — train your own local TTS voice")
    p.add_argument("--port", type=int, default=5003)
    p.add_argument("--out", type=str, default=os.path.join(os.path.expanduser("~"), "forge"),
                   help="Working directory for datasets, runs and exported voices")
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    app = build_app(args.out)
    app.launch(server_name="127.0.0.1", server_port=args.port, share=False, inbrowser=True)


if __name__ == "__main__":
    main()
