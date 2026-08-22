#!/usr/bin/env python3
"""
Watch files and auto-commit on changes. Optionally push to origin.

Usage:
  python3 scripts/auto_git_watcher.py --paths . --push

Install dependency:
  pip install watchdog
"""
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


def run_cmd(cmd, cwd=None):
    result = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, repo_path: Path, push: bool, debounce: float = 1.0):
        super().__init__()
        self.repo_path = repo_path
        self.push = push
        self.debounce = debounce
        self._timer = None
        self._lock = threading.Lock()

    def on_any_event(self, event):
        # ignore changes in .git
        if '/.git/' in str(event.src_path) or str(event.src_path).endswith('.git'):
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self._do_commit)
            self._timer.start()

    def _do_commit(self):
        # Stage all changes
        code, out, err = run_cmd(['git', 'add', '-A'], cwd=str(self.repo_path))
        if code != 0:
            print('git add failed:', err)
            return

        # Check staged files
        code, files_out, files_err = run_cmd(['git', 'diff', '--cached', '--name-only'], cwd=str(self.repo_path))
        if code != 0:
            print('git diff --cached failed:', files_err)
            return

        files = [f for f in files_out.splitlines() if f]
        if not files:
            # Nothing to commit
            return

        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        commit_msg = f"auto-save: {', '.join(files)} @ {ts}"
        code, out, err = run_cmd(['git', 'commit', '-m', commit_msg], cwd=str(self.repo_path))
        if code != 0:
            # If nothing to commit, git returns non-zero sometimes
            if 'nothing to commit' in err.lower():
                return
            print('git commit failed:', err)
            return

        print('Committed:', commit_msg)

        if self.push:
            # determine current branch
            code, branch, berr = run_cmd(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=str(self.repo_path))
            if code != 0:
                print('failed to get branch:', berr)
                return
            branch = branch.strip()
            print('Pushing to origin', branch)
            code, pout, perr = run_cmd(['git', 'push', 'origin', branch], cwd=str(self.repo_path))
            if code != 0:
                print('git push failed:', perr)
            else:
                print('Pushed to origin', branch)


def main():
    p = argparse.ArgumentParser(description='Auto-commit watcher for a git repo')
    p.add_argument('--paths', nargs='+', default=['.'], help='Paths to watch (default: .)')
    p.add_argument('--push', action='store_true', help='Attempt to push after commit')
    p.add_argument('--debounce', type=float, default=1.0, help='Debounce seconds')
    args = p.parse_args()

    repo_path = Path('.').resolve()
    if not (repo_path / '.git').exists():
        print('Not a git repository:', repo_path)
        sys.exit(1)

    handler = DebouncedHandler(repo_path=repo_path, push=args.push, debounce=args.debounce)
    observer = Observer()
    for pth in args.paths:
        path = Path(pth)
        if not path.exists():
            print('Path does not exist, skipping:', pth)
            continue
        observer.schedule(handler, str(path), recursive=True)

    observer.start()
    print('Watching', args.paths, 'push=' + str(args.push))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == '__main__':
    main()
