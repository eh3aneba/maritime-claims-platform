"""Synthetic hosted proof only. Never merge this disposable branch into main."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

TARGET = '998858f31d8c6ff8b8a2fe4b1184d787975efdf3'


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['produce', 'consume', 'gate'])
    parser.add_argument('--case', default='valid')
    args = parser.parse_args()
    frozen = Path('frozen').resolve()
    selector = frozen / 'scripts/backend_shard_selector.py'
    temporary = Path(os.environ['RUNNER_TEMP'])
    manifest = temporary / 'proof-manifest/backend-nodes.json'
    if args.operation == 'produce':
        if args.case == 'post-expiry-recovery' and os.environ['GITHUB_RUN_ATTEMPT'] == '1':
            # Seed the retry with the real, still-valid candidate artifact. On
            # rerun-all a fresh synthetic collection is produced instead.
            import datetime
            expiry = datetime.datetime.fromisoformat('2026-11-03T14:45:43+00:00')
            if datetime.datetime.now(datetime.timezone.utc) >= expiry:
                raise RuntimeError('cannot seed a pre-expiry observation after expiry')
            run = json.loads(subprocess.check_output(['gh', 'api',
                'repos/eh3aneba/maritime-claims-platform/actions/runs/41389632800']))
            if run['run_attempt'] != 2 or run['head_sha'] != TARGET:
                raise RuntimeError('originating artifact attempt changed')
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write('origin_run=41389632800\nartifact=backend-collection-2\n'
                    'digest=550ae6218cc97f2f880479f83ef585ecebe1d4802099a7006cb5de78788f31c2\n')
            print('Seeded reference to real pre-expiry artifact; no replacement uploaded.')
            return 0
        # An explicit synthetic collector shim exercises the unchanged producer
        # CLI. It is not a substitute for full backend collection or coverage.
        shim = temporary / 'synthetic-collector'
        shim.mkdir(exist_ok=True)
        executable = shim / 'pytest'
        executable.write_text('#!/usr/bin/env python3\nimport sys\n'
            + ('print("tests/test_synthetic.py::test_partial"); sys.exit(17)\n'
               if args.case == 'producer-failure' else
               'print("\\n".join(f"tests/test_synthetic.py::test_{n}" for n in range(2000)))\nprint("2000 tests collected in 0.1s")\n'))
        executable.chmod(0o700)
        manifest.parent.mkdir(exist_ok=True)
        environment = {**os.environ, 'PATH': str(shim) + os.pathsep + os.environ['PATH']}
        result = subprocess.run([sys.executable, str(selector), '--shards', '64',
            '--write-manifest', str(manifest), '--commit', TARGET],
            cwd=frozen / 'apps/api', env=environment, capture_output=True)
        if args.case == 'producer-failure':
            if result.returncode == 0 or manifest.exists() or result.stdout:
                raise RuntimeError('failed producer emitted output')
            print('Synthetic partial collection rejected; producer job deliberately fails.')
            return 17  # Real hosted failure; dependent consumers must be skipped.
        if result.returncode:
            raise RuntimeError('synthetic producer unexpectedly failed')
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        if result.stdout.decode().strip() != 'manifest_sha256=' + digest:
            raise RuntimeError('producer output checksum mismatch')
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'digest={digest}\nartifact=ci-v2-proof-{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}\n')
            output.write(f'origin_run={os.environ["GITHUB_RUN_ID"]}\n')
        print('Unchanged producer CLI generated checksum-bound synthetic fixture.')
        return 0
    if args.operation == 'consume':
        digest = os.environ['MANIFEST_SHA256']
        if args.case != 'missing-artifact':
            raw = manifest.read_bytes()
            if args.case == 'corrupt':
                manifest.write_bytes(raw + b'corruption')
            elif args.case == 'wrong-digest':
                digest = '0' * 64
            elif args.case in {'stale', 'wrong-tree', 'duplicate', 'missing-node'}:
                doc = json.loads(raw)
                if args.case == 'stale': doc['commit'] = '0' * 40
                if args.case == 'wrong-tree': doc['tree'] = '0' * 40
                if args.case == 'duplicate': doc['nodes'][-1] = doc['nodes'][0]
                if args.case == 'missing-node': doc['nodes'].pop()
                manifest.write_text(json.dumps(doc))
                # Validate schema/identity even with a matching checksum.
                digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        command = [sys.executable, str(selector), '--shard', '0', '--shards', '64',
                   '--manifest', str(manifest), '--commit', TARGET, '--manifest-sha256', digest]
        result = subprocess.run(command, cwd=frozen / 'apps/api', capture_output=True)
        valid = args.case == 'valid'
        if valid:
            if result.returncode or not result.stdout.endswith(b'\0'):
                raise RuntimeError('valid fixture rejected')
        elif result.returncode == 0 or result.stdout:
            raise RuntimeError('invalid fixture did not fail closed')
        print(json.dumps({'case': args.case, 'exit_status': result.returncode,
                          'stdout_empty': not bool(result.stdout), 'expected_rejection': not valid}))
        return 0
    # Execute the exact frozen aggregate shell with actual hosted dependency
    # results. A failed producer must never be accepted by the original gate.
    workflow = (frozen / '.github/workflows/backend-premerge.yml').read_text()
    gate = workflow.split('      - name: Enforce complete Backend CI selection\n', 1)[1]
    gate = gate.split('        run: |\n', 1)[1]
    shell = '\n'.join(line[10:] for line in gate.splitlines() if line.startswith('          '))
    producer_failure = os.environ['PROOF_MODE'] == 'producer-failure'
    retry_failure = os.environ['PROOF_MODE'] in {'rerun-recovery', 'post-expiry-recovery'} and os.environ['SHARD_RESULT'] == 'failure'
    expected_failure = producer_failure or retry_failure
    if producer_failure and (os.environ['COLLECTION_RESULT'] != 'failure' or os.environ['SHARD_RESULT'] != 'skipped'):
        raise RuntimeError('unexpected real dependency results')
    if retry_failure and os.environ['COLLECTION_RESULT'] != 'success':
        raise RuntimeError('retry did not preserve successful producer')
    if not expected_failure and (os.environ['COLLECTION_RESULT'] != 'success' or os.environ['SHARD_RESULT'] != 'success'):
        raise RuntimeError('proof consumers did not validate')
    result = subprocess.run(['bash', '-c', shell], capture_output=True)
    if (result.returncode != 0) != expected_failure:
        raise RuntimeError('original aggregate shell accepted wrong outcome')
    print(json.dumps({'mode': os.environ['PROOF_MODE'], 'original_aggregate_exit': result.returncode,
                      'producer': os.environ['COLLECTION_RESULT'], 'consumers': os.environ['SHARD_RESULT']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
