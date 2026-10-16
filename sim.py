"""Физика Fart Together без графики: трасса, препятствия, плот.

Мир двумерный (вид сверху): x — поперёк, y — вдоль трассы (уменьшается
по ходу движения), s = -y — пройденная дистанция. 3D-рендер только рисует
это состояние, а по сети передаётся снимок из snapshot().
"""
import math
import random

TRACK_LEN = 20000
RAFT_R = 62
CHECKPOINT_STEP = 2000

ANIMALS = [
    # имя, вид, клавиша в режиме «вместе»
    ("Лягуха", "frog", "q"),
    ("Мишаня", "bear", "p"),
    ("Бегемот", "hippo", "z"),
    ("Мартын", "monkey", "m"),
]


# ---------------------------------------------------------------- track
def center_x(s):
    return (260 * math.sin(s / 900.0) + 140 * math.sin(s / 2300.0 + 1.3)
            + 60 * math.sin(s / 410.0 + 0.4) * min(1.0, max(0.0, s) / 3000.0))


def half_width(s):
    if s < 600 or s > TRACK_LEN - 400:
        return 300
    return 235 + 55 * math.sin(s / 1300.0 + 0.7)


# участки с бортиками; между ними края открыты и с горки можно вылететь
RAILS = [(-3000, 1800), (3400, 4700), (6500, 7600), (9300, 10200), (12400, 13300),
         (15200, 16000), (18000, TRACK_LEN + 4000)]


def has_rail(s):
    return any(a <= s <= b for a, b in RAILS)


def flow_dir(s):
    d = (center_x(s + 5) - center_x(s - 5)) / 10.0
    ln = math.hypot(d, 1)
    return d / ln, -1 / ln


# ---------------------------------------------------------------- obstacles
class Hammer:
    """Маятник-молот: голова ходит поперёк трассы."""
    kind = "hammer"

    def __init__(self, s, side, speed, phase):
        self.s, self.side, self.speed, self.phase = s, side, speed, phase
        self.r = 46

    def swing(self, t):
        return math.sin(t * self.speed + self.phase)

    def head(self, t):
        return center_x(self.s) + half_width(self.s) * 0.9 * self.swing(t), -self.s

    def collide(self, t, p):
        hx, hy = self.head(t)
        return hx, hy, self.r


class Spinner:
    """Крутящаяся палка с шипами поперёк трассы."""
    kind = "spinner"

    def __init__(self, s, speed, length=0.75):
        self.s, self.speed, self.len = s, speed, length

    def angle(self, t):
        return t * self.speed

    def half_len(self):
        return half_width(self.s) * self.len

    def ends(self, t):
        cx = center_x(self.s)
        a, L = self.angle(t), self.half_len()
        return ((cx - L * math.cos(a), -self.s - L * math.sin(a)),
                (cx + L * math.cos(a), -self.s + L * math.sin(a)))

    def collide(self, t, p):
        (ax, ay), (bx, by) = self.ends(t)
        dx, dy = bx - ax, by - ay
        k = max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        return ax + dx * k, ay + dy * k, 16


class Mine:
    """Шипастая мина, плавает из стороны в сторону."""
    kind = "mine"

    def __init__(self, s, speed, phase):
        self.s, self.speed, self.phase = s, speed, phase
        self.r = 34

    def pos(self, t):
        cx, hw = center_x(self.s), half_width(self.s)
        return (cx + hw * 0.65 * math.sin(t * self.speed + self.phase),
                -self.s + 20 * math.sin(t * 2 + self.phase))

    def collide(self, t, p):
        x, y = self.pos(t)
        return x, y, self.r


def build_obstacles():
    rnd = random.Random(7)
    obs = []
    s = 1500
    while s < TRACK_LEN - 900:
        kind = rnd.choice(["hammer", "hammer", "spinner", "mine", "mine"])
        if kind == "hammer":
            obs.append(Hammer(s, rnd.choice([-1, 1]), rnd.uniform(1.2, 2.0), rnd.uniform(0, 6)))
        elif kind == "spinner":
            obs.append(Spinner(s, rnd.choice([-1, 1]) * rnd.uniform(0.9, 1.6)))
        else:
            obs.append(Mine(s, rnd.uniform(0.6, 1.3), rnd.uniform(0, 6)))
            if rnd.random() < 0.5:
                obs.append(Mine(s + 160, rnd.uniform(0.6, 1.3), rnd.uniform(0, 6)))
        s += rnd.randint(650, 1050)
    return obs


# ---------------------------------------------------------------- world
class Seat:
    def __init__(self, idx, name, kind, key):
        self.idx, self.name, self.kind, self.key = idx, name, kind, key
        self.gas = 100.0
        self.empty = False
        self.farting = False


class World:
    def __init__(self):
        self.seats = [Seat(i, *a) for i, a in enumerate(ANIMALS)]
        self.obstacles = build_obstacles()
        self.state = "menu"
        self.best = None
        self.new_record = False
        self.events = []  # «hit», «fall», «checkpoint» — для звуков и тряски камеры
        self.reset()

    def reset(self):
        self.x, self.y = center_x(0), 0.0
        self.vx, self.vy = 0.0, -60.0
        self.ang, self.spin = 0.0, 0.0
        self.t = 0.0
        self.time = 0.0
        self.falls = 0
        self.checkpoint = 0
        self.falling = 0.0
        self.fall_dir = 1
        self.hit_cd = 0.0
        self.countdown = 3.0
        self.new_record = False
        for s in self.seats:
            s.gas, s.empty, s.farting = 100.0, False, False
        self.flash = ""
        self.flash_t = 0.0

    def seat_dir(self, i):
        a = self.ang + i * math.pi / 2 - math.pi / 2
        return math.cos(a), math.sin(a)

    def say(self, text):
        self.flash, self.flash_t = text, 1.4

    def auto_farts(self, dx, dy):
        """Для соло-режима: какие звери должны пукнуть, чтобы толкнуть плот в (dx, dy)."""
        if not dx and not dy:
            return [False] * 4
        ln = math.hypot(dx, dy)
        dx, dy = dx / ln, dy / ln
        res = []
        for i in range(4):
            sx, sy = self.seat_dir(i)
            res.append(-sx * dx - sy * dy > 0.38)
        return res

    def update(self, dt, want):
        self.t += dt
        if self.flash_t > 0:
            self.flash_t -= dt
        if self.state != "play":
            for s in self.seats:
                s.farting = False
            return
        if self.countdown > 0:
            self.countdown -= dt
            return
        self.time += dt

        if self.falling > 0:
            self.falling -= dt
            if self.falling <= 0:
                self.respawn()
            return

        s = -self.y
        fx, fy = flow_dir(s)
        current = 230 + 60 * min(1, s / 6000)
        ax = (fx * current - self.vx) * 0.9
        ay = (fy * current - self.vy) * 0.9

        for i, seat in enumerate(self.seats):
            on = want[i] and not seat.empty
            seat.farting = on
            if on:
                seat.gas -= 55 * dt
                if seat.gas <= 0:
                    seat.gas, seat.empty = 0, True
                sx, sy = self.seat_dir(i)
                ax += -sx * 900
                ay += -sy * 900
                self.spin += (1 if i % 2 else -1) * 0.9 * dt
            else:
                seat.gas = min(100, seat.gas + 22 * dt)
                if seat.empty and seat.gas > 30:
                    seat.empty = False

        self.vx += ax * dt
        self.vy += ay * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.spin *= (1 - 0.8 * dt)
        self.spin += (random.random() - 0.5) * 0.4 * dt
        self.ang += self.spin * dt

        s = -self.y
        if s < -200:
            self.y = 200
            self.vy = abs(self.vy) * -0.5
        cx, hw = center_x(s), half_width(s)
        off = self.x - cx
        if abs(off) > hw - RAFT_R * 0.6:
            if has_rail(s):
                side = 1 if off > 0 else -1
                self.x = cx + side * (hw - RAFT_R * 0.6)
                if self.vx * side > 0:
                    self.vx = -self.vx * 0.6
                    self.spin += side * 1.5
            elif abs(off) > hw + 10:
                self.start_fall(1 if off > 0 else -1)

        if self.hit_cd > 0:
            self.hit_cd -= dt
        for ob in self.obstacles:
            if abs(ob.s - s) > 400:
                continue
            ox, oy, r = ob.collide(self.t, (self.x, self.y))
            dx, dy = self.x - ox, self.y - oy
            d = math.hypot(dx, dy)
            if r + RAFT_R > d > 0.01:
                nx, ny = dx / d, dy / d
                self.x, self.y = ox + nx * (r + RAFT_R), oy + ny * (r + RAFT_R)
                if self.hit_cd <= 0:
                    self.vx += nx * 650
                    self.vy += ny * 650
                    self.spin += random.choice([-1, 1]) * 4
                    self.hit_cd = 0.35
                    self.events.append("hit")

        cp = int(max(0, s) // CHECKPOINT_STEP) * CHECKPOINT_STEP
        if cp > self.checkpoint:
            self.checkpoint = cp
            self.say("Чекпоинт!")
            self.events.append("checkpoint")
        if s >= TRACK_LEN:
            self.finish()

    def start_fall(self, side):
        self.falling = 1.2
        self.fall_dir = side
        self.falls += 1
        self.say("Плюх! +3 сек")
        self.time += 3
        self.events.append("fall")

    def respawn(self):
        s = max(0, self.checkpoint)
        self.x, self.y = center_x(s), -s
        fx, fy = flow_dir(s)
        self.vx, self.vy = fx * 80, fy * 80
        self.spin = 0

    def finish(self):
        self.state = "finish"
        self.new_record = self.best is None or self.time < self.best
        if self.new_record:
            self.best = self.time

    # ------------------------------------------------------------ network
    def snapshot(self, players):
        return {
            "type": "state", "st": self.state, "x": round(self.x, 1), "y": round(self.y, 1),
            "vx": round(self.vx, 1), "vy": round(self.vy, 1), "a": round(self.ang, 3),
            "sp": round(self.spin, 3), "t": round(self.t, 3), "tm": round(self.time, 2),
            "fl": round(self.falling, 2), "fd": self.fall_dir, "cp": self.checkpoint,
            "falls": self.falls, "cd": round(self.countdown, 2), "fs": self.flash,
            "ft": round(self.flash_t, 2), "nr": self.new_record, "pl": players,
            "g": [[round(st.gas, 1), st.empty, st.farting] for st in self.seats],
        }

    def apply_snapshot(self, st, age, dt):
        """Клиент: подтягивает локальное состояние к снимку хоста."""
        prev_falls = self.falls
        self.state = st["st"]
        self.vx, self.vy, self.spin = st["vx"], st["vy"], st["sp"]
        moving = st["st"] == "play" and st["cd"] <= 0 and st["fl"] <= 0
        tx = st["x"] + (self.vx * age if moving else 0)
        ty = st["y"] + (self.vy * age if moving else 0)
        if math.hypot(tx - self.x, ty - self.y) > 200:
            self.x, self.y = tx, ty
        else:
            self.x += (tx - self.x) * min(1, dt * 15)
            self.y += (ty - self.y) * min(1, dt * 15)
        self.ang = st["a"] + (self.spin * age if moving else 0)
        self.t = st["t"] + age
        self.time, self.falling, self.checkpoint = st["tm"], st["fl"], st["cp"]
        self.fall_dir = st.get("fd", 1)
        self.falls, self.countdown, self.new_record = st["falls"], st["cd"], st["nr"]
        self.flash, self.flash_t = st["fs"], st["ft"]
        for i, (gas, empty, farting) in enumerate(st["g"]):
            seat = self.seats[i]
            seat.gas, seat.empty, seat.farting = gas, empty, farting
        if self.falls > prev_falls:
            self.events.append("fall")
