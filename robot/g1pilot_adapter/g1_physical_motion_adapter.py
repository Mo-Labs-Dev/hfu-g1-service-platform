#!/usr/bin/env python3
"""G1 Studio V3: read-only robot monitor and stop-request controller.

No walking, posture or FSM-changing commands are exposed.
A successful StopMove SDK call is NOT physical stop verification.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.getenv('G1_MOTION_HOST', '127.0.0.1')
PORT = int(os.getenv('G1_MOTION_PORT', '8770'))
INTERFACE = os.getenv('G1_ROBOT_INTERFACE', 'enP2p1s0')
POLL_SECONDS = 1.0
STALE_SECONDS = 3.0
SDK_TIMEOUT_SECONDS = 1.0

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('g1-motion-v3')
state_lock = threading.RLock()
sdk_lock = threading.RLock()
shutdown = threading.Event()
client = None
fsm_id_api = None
fsm_mode_api = None

state = {
    'mode': 'physical_disarmed',
    'armed': False,
    'physical_motion_enabled': False,
    'velocity_commands_available': False,
    'stop_verified': False,
    'moving': False,
    'velocity': [0.0, 0.0, 0.0],
    'sdk_available': False,
    'connected': False,
    'fsm_id': None,
    'fsm_mode': None,
    'locomotion_mode': False,
    'error': None,
    'last_status_monotonic': None,
    'last_stop_request_monotonic': None,
    'last_stop_request_ok': None,
    'stop_request_count': 0,
}


def initialize_sdk():
    global client, fsm_id_api, fsm_mode_api
    try:
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize
        from unitree_sdk2py.g1.loco.g1_loco_client import LocoClient
        from unitree_sdk2py.g1.loco.g1_loco_api import (
            ROBOT_API_ID_LOCO_GET_FSM_ID,
            ROBOT_API_ID_LOCO_GET_FSM_MODE,
        )
        ChannelFactoryInitialize(0, INTERFACE)
        instance = LocoClient()
        instance.SetTimeout(SDK_TIMEOUT_SECONDS)
        instance.Init()
        client = instance
        fsm_id_api = ROBOT_API_ID_LOCO_GET_FSM_ID
        fsm_mode_api = ROBOT_API_ID_LOCO_GET_FSM_MODE
        with state_lock:
            state['sdk_available'] = True
            state['error'] = None
        log.info('SDK initialized on %s; walking disabled', INTERFACE)
    except Exception as exc:
        with state_lock:
            state['sdk_available'] = False
            state['connected'] = False
            state['error'] = str(exc)
        log.exception('SDK initialization failed')


def read_integer(api):
    with sdk_lock:
        code, response = client._Call(api, '{}')
    if code != 0:
        raise RuntimeError(f'SDK RPC failed: {code}')
    value = json.loads(response).get('data')
    if type(value) is not int:
        raise ValueError(f'Unexpected RPC response: {response!r}')
    return value


def monitor():
    while not shutdown.is_set():
        if client is not None:
            try:
                fsm = read_integer(fsm_id_api)
                mode = read_integer(fsm_mode_api)
                with state_lock:
                    state['connected'] = True
                    state['fsm_id'] = fsm
                    state['fsm_mode'] = mode
                    state['locomotion_mode'] = (fsm == 500)
                    state['last_status_monotonic'] = time.monotonic()
                    state['error'] = None
            except Exception as exc:
                with state_lock:
                    state['connected'] = False
                    state['locomotion_mode'] = False
                    state['fsm_id'] = None
                    state['fsm_mode'] = None
                    state['error'] = str(exc)
                log.warning('Status polling failed: %s', exc)
        shutdown.wait(POLL_SECONDS)


def request_stop():
    """Send StopMove to hardware. Does not prove physical halt."""
    with state_lock:
        state['armed'] = False
        state['moving'] = False
        state['velocity'] = [0.0, 0.0, 0.0]
        state['mode'] = 'physical_disarmed'
        state['stop_verified'] = False
        state['last_stop_request_monotonic'] = time.monotonic()
        state['stop_request_count'] += 1
        state['last_stop_request_ok'] = False

    if client is None:
        return False, 'SDK unavailable'
    try:
        with sdk_lock:
            client.StopMove()
        with state_lock:
            state['last_stop_request_ok'] = True
        log.info('StopMove request completed (physical halt NOT verified)')
        return True, None
    except Exception as exc:
        with state_lock:
            state['error'] = f'StopMove failed: {exc}'
        log.exception('StopMove request failed')
        return False, str(exc)


def snapshot():
    with state_lock:
        result = dict(state)
    timestamp = result.pop('last_status_monotonic')
    last_stop = result.pop('last_stop_request_monotonic')
    fresh = timestamp is not None and time.monotonic() - timestamp < STALE_SECONDS
    result['connected'] = bool(result['connected'] and fresh)
    if not result['connected']:
        result['locomotion_mode'] = False
    result['robot_interface'] = INTERFACE
    result['watchdog_timeout_ms'] = 300
    result['watchdog_active'] = False
    result['limits'] = {'linear': 0.10, 'angular': 0.15}
    result['physical_stop_command_sent'] = bool(result['last_stop_request_ok'])
    result['seconds_since_stop_request'] = (
        round(time.monotonic() - last_stop, 2) if last_stop is not None else None
    )
    return result


class Handler(BaseHTTPRequestHandler):
    def respond(self, code, data):
        body = json.dumps(data).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if self.path in ('/health', '/physical-motion/status'):
            self.respond(200, snapshot())
        else:
            self.respond(404, {'error': 'Not found'})

    def do_POST(self):
        if self.path == '/physical-motion/stop':
            ok, error = request_stop()
            self.respond(200 if ok else 503, {
                'status': 'stop_requested' if ok else 'stop_request_failed',
                'physical_stop_command_sent': ok,
                'stop_verified': False,
                'error': error,
            })
        elif self.path in ('/physical-motion', '/physical-motion/arm'):
            self.respond(403, {
                'error': 'Physical walking safety-locked',
                'physical_motion_enabled': False,
                'stop_verified': False,
            })
        else:
            self.respond(404, {'error': 'Not found'})


def main():
    initialize_sdk()
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    log.info('V3 listening on %s:%d (physical walking locked)', HOST, PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown.set()
        server.server_close()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()