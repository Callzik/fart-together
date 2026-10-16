"""Простая сеть для Fart Together: один игрок хостит, остальные подключаются по TCP.

Хост считает всю физику и рассылает состояние; клиенты присылают только
«пукаю / не пукаю» за своего зверя. Сообщения — JSON, по одному на строку.
"""
import json
import socket
import threading
import time

PORT = 5555
MAX_PLAYERS = 4


def _send(sock, obj):
    sock.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())


def _lines(sock):
    buf = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line:
                yield json.loads(line)


def local_ips():
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    ips.discard("127.0.0.1")
    return sorted(ips) or ["127.0.0.1"]


class Host:
    """Хост: место 0 — сам хост, места 1..3 раздаются подключившимся."""

    def __init__(self, port=PORT):
        self.port = port
        self.lock = threading.Lock()
        self.clients = {}  # seat -> socket
        self.inputs = [False] * MAX_PLAYERS
        self.error = None
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("0.0.0.0", port))
        self.srv.listen(8)
        self.running = True
        threading.Thread(target=self._accept, daemon=True).start()

    def seats_taken(self):
        with self.lock:
            return [0] + sorted(self.clients)

    def _accept(self):
        while self.running:
            try:
                sock, _ = self.srv.accept()
            except OSError:
                return
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.lock:
                free = [i for i in range(1, MAX_PLAYERS) if i not in self.clients]
                seat = free[0] if free else None
                if seat is not None:
                    self.clients[seat] = sock
            if seat is None:
                try:
                    _send(sock, {"type": "full"})
                    sock.close()
                except OSError:
                    pass
                continue
            try:
                _send(sock, {"type": "welcome", "seat": seat})
            except OSError:
                self._drop(seat)
                continue
            threading.Thread(target=self._read, args=(seat, sock), daemon=True).start()

    def _read(self, seat, sock):
        try:
            for msg in _lines(sock):
                if msg.get("type") == "in":
                    self.inputs[seat] = bool(msg.get("f"))
        except (OSError, ValueError):
            pass
        self._drop(seat)

    def _drop(self, seat):
        with self.lock:
            sock = self.clients.pop(seat, None)
        self.inputs[seat] = False
        if sock:
            try:
                sock.close()
            except OSError:
                pass

    def broadcast(self, state):
        data = (json.dumps(state, separators=(",", ":")) + "\n").encode()
        with self.lock:
            items = list(self.clients.items())
        for seat, sock in items:
            try:
                sock.sendall(data)
            except OSError:
                self._drop(seat)

    def close(self):
        self.running = False
        try:
            self.srv.close()
        except OSError:
            pass
        for seat in list(self.clients):
            self._drop(seat)


class Client:
    def __init__(self, address):
        host, _, port = address.strip().partition(":")
        self.seat = None
        self.state = None
        self.state_time = 0.0
        self.error = None
        self.connected = False
        self.sock = None
        self.last_sent = None
        self.last_sent_t = 0.0
        threading.Thread(target=self._run, args=(host, int(port or PORT)), daemon=True).start()

    def _run(self, host, port):
        try:
            self.sock = socket.create_connection((host, port), timeout=6)
            self.sock.settimeout(None)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.connected = True
            for msg in _lines(self.sock):
                kind = msg.get("type")
                if kind == "welcome":
                    self.seat = msg["seat"]
                elif kind == "full":
                    self.error = "Все 4 места заняты"
                    return
                elif kind == "state":
                    self.state = msg
                    self.state_time = time.monotonic()
            self.error = "Хост закрыл игру"
        except (OSError, ValueError) as e:
            self.error = f"Не удалось подключиться: {e}"
        finally:
            self.connected = False

    def send_input(self, farting):
        if not self.connected or self.sock is None:
            return
        now = time.monotonic()
        if farting == self.last_sent and now - self.last_sent_t < 0.25:
            return
        try:
            _send(self.sock, {"type": "in", "f": farting})
            self.last_sent, self.last_sent_t = farting, now
        except OSError:
            self.connected = False

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass
