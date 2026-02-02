import argparse
import subprocess
import sys
from pathlib import Path

REPOS = [
    ("HarmoneyOpenEye", "https://github.com/WinWang/HarmoneyOpenEye.git"),
    ("Harmony-arkts-movie-music-app-ui", "https://github.com/wuyuanwuhui99/Harmony-arkts-movie-music-app-ui.git"),
    ("biandan-satge", "https://github.com/AlthenWaySatan/biandan-satge.git"),
    ("ArkTS-wphui1.0", "https://gitee.com/boring-music/ArkTS-wphui1.0.git"),
		("codelabs", "https://gitee.com/harmonyos/codelabs.git"),
]

def run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)

def main(argv: list[str] | None = None) -> None:
    repo_root = Path(__file__).resolve().parents[1]   # ...\harmony-ptg-generate-llm

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "base_dir",
        nargs="?",
        help="基础目录；仓库会克隆到该目录下的 projects/ 里（例：E:/HarmonyOS）",
    )
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    base_dir = Path(args.base_dir) if args.base_dir else repo_root.parent
    target_root = base_dir / "projects"
    target_root.mkdir(parents=True, exist_ok=True)
    print(f"[target] {target_root}")

    # 仓库逐个克隆
    for name, url in REPOS:
        dest = target_root / name
        run(["git", "clone", url, str(dest)])

    print("[done]")


if __name__ == "__main__":
    main()