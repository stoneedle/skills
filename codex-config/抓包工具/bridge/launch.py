"""Start the bridge outside the invoking terminal/app's Windows job lifecycle."""
import ctypes
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    pythonw = Path(sys.argv[1])
    # Hidden alone does not detach a child from Windows job termination.
    with (ROOT/'launcher.log').open('ab', buffering=0) as log:
        child = subprocess.Popen([str(pythonw), str(ROOT/'bridge.py')], cwd=ROOT,
            stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP |
                          subprocess.CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.IsProcessInJob.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    member = ctypes.c_int()
    if not k.IsProcessInJob(int(child._handle), None, ctypes.byref(member)):
        child.kill()
        raise ctypes.WinError(ctypes.get_last_error())
    # The venv redirector can establish its own job immediately. Membership in
    # any job is not a failure; test_lifecycle checks the invoking job exactly.
    result = {'time': datetime.now().astimezone().isoformat(), 'launcher_pid': child.pid,
              'launcher_in_job_after_start': bool(member.value),
              'creation_flags': 'DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP|CREATE_BREAKAWAY_FROM_JOB',
              'action': 'start_detached'}
    with (ROOT/'lifecycle.jsonl').open('a', encoding='utf-8') as audit:
        audit.write(json.dumps(result) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
