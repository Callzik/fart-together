"""Fart Together — кооперативная гонка на надувном плоту.

Четыре зверя сидят на круглом плоту и плывут по водной горке.
Плот толкается только газом: зверь пукает — плот летит в противоположную
от него сторону. Доплывите до финиша, не вылетев с горки и уворачиваясь
от молотов, крутилок и морских мин.
"""
import array
import json
import math
import os
import random
import sys

import pygame

W, H = 960, 720
FPS = 60
TRACK_LEN = 20000
RAFT_R = 62
CHECKPOINT_STEP = 2000
SAVE_FILE = os.path.join(os.path.expanduser("~"), ".fart_together.json")

SKY = (150, 205, 245)
CLIFF = (232, 128, 110)
CLIFF_DARK = (196, 96, 86)
WATER = (40, 140, 230)
WATER_LIGHT = (120, 195, 250)
RAIL = (80, 210, 190)
RAIL_DARK = (40, 160, 150)
RAFT_RING = (250, 205, 160)
RAFT_FLOOR = (120, 180, 80)
GAS = (170, 230, 40)
WHITE = (255, 255, 255)
BLACK = (20, 20, 30)

ANIMALS = [
    # name, body colour, belly colour, kind, key, key label
    ("Лягуха", (110, 190, 60), (190, 230, 120), "frog", pygame.K_q, "Q"),
    ("Мишаня", (70, 70, 80), (130, 130, 140), "bear", pygame.K_p, "P"),
    ("Бегемот", (60, 110, 160), (120, 170, 210), "hippo", pygame.K_z, "Z"),
    ("Мартын", (230, 140, 70), (250, 200, 150), "monkey", pygame.K_m, "M"),
]


# ---------------------------------------------------------------- track
def center_x(s):
    return (260 * math.sin(s / 900.0) + 140 * math.sin(s / 2300.0 + 1.3)
            + 60 * math.sin(s / 410.0 + 0.4) * min(1.0, s / 3000.0))


def half_width(s):
    if s < 600 or s > TRACK_LEN - 400:
        return 300
    return 235 + 55 * math.sin(s / 1300.0 + 0.7)


# segments with side walls; between them the edges are open and you can fall
RAILS = [(-1000, 1800), (3400, 4700), (6500, 7600), (9300, 10200), (12400, 13300),
         (15200, 16000), (18000, TRACK_LEN + 2000)]


def has_rail(s):
    return any(a <= s <= b for a, b in RAILS)


def flow_dir(s):
    d = (center_x(s + 5) - center_x(s - 5)) / 10.0
    ln = math.hypot(d, 1)
    return d / ln, -1 / ln  # world y grows down, track goes up


# ---------------------------------------------------------------- sound
def make_fart_sound(seed):
    rnd = random.Random(seed)
    rate = 22050
    dur = 0.35 + rnd.random() * 0.25
    base = 70 + rnd.random() * 60
    n = int(rate * dur)
    buf = array.array("h")
    phase = 0.0
    for i in range(n):
        t = i / rate
        f = base * (1 + 0.35 * math.sin(t * 38 + seed)) * (1 - 0.3 * t / dur)
        phase += f / rate
        v = 1.0 if (phase % 1.0) < 0.35 else -0.6
        v += rnd.uniform(-0.5, 0.5)
        env = min(1.0, t * 40) * (1 - t / dur) ** 1.5
        s = int(max(-1, min(1, v * env * 0.5)) * 32000)
        buf.append(s)
        buf.append(s)
    return pygame.mixer.Sound(buffer=buf.tobytes())


# ---------------------------------------------------------------- obstacles
class Hammer:
    """Swinging hammer: the head sweeps across the track."""

    def __init__(self, s, side, speed, phase):
        self.s, self.side, self.speed, self.phase = s, side, speed, phase
        self.r = 46

    def head(self, t):
        cx, hw = center_x(self.s), half_width(self.s)
        return cx + hw * 0.9 * math.sin(t * self.speed + self.phase), -self.s

    def pivot(self):
        cx, hw = center_x(self.s), half_width(self.s)
        return cx + self.side * (hw + 90), -self.s - 40

    def collide(self, t, p):
        hx, hy = self.head(t)
        return hx, hy, self.r

    def draw(self, surf, cam, t):
        px, py = cam.to_screen(*self.pivot())
        hx, hy = cam.to_screen(*self.head(t))
        pygame.draw.line(surf, (240, 120, 40), (px, py), (hx, hy), 16)
        pygame.draw.circle(surf, (200, 90, 30), (px, py), 18)
        rect = pygame.Rect(0, 0, 110, 70)
        rect.center = (hx, hy)
        pygame.draw.rect(surf, RAIL_DARK, rect.move(0, 6), border_radius=18)
        pygame.draw.rect(surf, RAIL, rect, border_radius=18)
        pygame.draw.circle(surf, (250, 100, 30), (hx - 38, hy), 22)
        pygame.draw.circle(surf, (250, 100, 30), (hx + 38, hy), 22)


class Spinner:
    """Rotating bar with spikes in the middle of the track."""

    def __init__(self, s, speed, length=0.75):
        self.s, self.speed, self.len = s, speed, length

    def ends(self, t):
        cx, hw = center_x(self.s), half_width(self.s)
        a = t * self.speed
        L = hw * self.len
        return (cx - L * math.cos(a), -self.s - L * math.sin(a)), (cx + L * math.cos(a), -self.s + L * math.sin(a))

    def collide(self, t, p):
        (ax, ay), (bx, by) = self.ends(t)
        dx, dy = bx - ax, by - ay
        k = max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
        return ax + dx * k, ay + dy * k, 16

    def draw(self, surf, cam, t):
        a, b = self.ends(t)
        a, b = cam.to_screen(*a), cam.to_screen(*b)
        pygame.draw.line(surf, (120, 60, 120), (a[0], a[1] + 6), (b[0], b[1] + 6), 22)
        pygame.draw.line(surf, (220, 80, 200), a, b, 22)
        for i in range(9):
            k = i / 8
            x, y = a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
            pygame.draw.circle(surf, WHITE, (int(x), int(y)), 6)
        c = cam.to_screen(center_x(self.s), -self.s)
        pygame.draw.circle(surf, (90, 90, 100), c, 20)


class Mine:
    """Spiky floating ball drifting from side to side."""

    def __init__(self, s, speed, phase):
        self.s, self.speed, self.phase = s, speed, phase
        self.r = 34

    def pos(self, t):
        cx, hw = center_x(self.s), half_width(self.s)
        return cx + hw * 0.65 * math.sin(t * self.speed + self.phase), -self.s + 20 * math.sin(t * 2 + self.phase)

    def collide(self, t, p):
        x, y = self.pos(t)
        return x, y, self.r

    def draw(self, surf, cam, t):
        x, y = cam.to_screen(*self.pos(t))
        for i in range(8):
            a = i * math.pi / 4 + t
            tip = (x + math.cos(a) * 50, y + math.sin(a) * 50)
            l = (x + math.cos(a - 0.3) * 30, y + math.sin(a - 0.3) * 30)
            r = (x + math.cos(a + 0.3) * 30, y + math.sin(a + 0.3) * 30)
            pygame.draw.polygon(surf, WHITE, [tip, l, r])
        pygame.draw.circle(surf, (190, 40, 50), (x, y), self.r)
        pygame.draw.circle(surf, (90, 170, 140), (x, y + 8), self.r - 6, width=8)
        pygame.draw.circle(surf, (240, 120, 120), (x - 10, y - 12), 8)


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


# ---------------------------------------------------------------- game objects
class Camera:
    def __init__(self):
        self.x, self.y = 0.0, 0.0
        self.shake = 0.0

    def follow(self, x, y, dt):
        self.x += (x - self.x) * min(1, dt * 4)
        self.y += (y - H * 0.18 - self.y) * min(1, dt * 6)
        self.shake = max(0, self.shake - dt * 30)

    def to_screen(self, x, y):
        sx = random.uniform(-self.shake, self.shake)
        sy = random.uniform(-self.shake, self.shake)
        return int(x - self.x + W / 2 + sx), int(y - self.y + H / 2 + sy)


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max", "r")

    def __init__(self, x, y, vx, vy, life, r):
        self.x, self.y, self.vx, self.vy, self.life, self.max, self.r = x, y, vx, vy, life, life, r


class Seat:
    def __init__(self, idx, data, sound):
        self.idx = idx
        self.name, self.color, self.belly, self.kind, self.key, self.label = data
        self.gas = 100.0
        self.empty = False
        self.farting = False
        self.sound = sound
        self.channel = None


class Game:
    def __init__(self, screen):
        self.screen = screen
        self.font = pygame.font.SysFont("arial", 18, bold=True)
        self.small = pygame.font.SysFont("arial", 13, bold=True)
        self.big = pygame.font.SysFont("arial", 64, bold=True)
        self.mid = pygame.font.SysFont("arial", 30, bold=True)
        self.audio = pygame.mixer.get_init() is not None
        sounds = [make_fart_sound(i) if self.audio else None for i in range(4)]
        self.seats = [Seat(i, a, sounds[i]) for i, a in enumerate(ANIMALS)]
        self.best = self.load_best()
        self.state = "menu"
        self.mode = "solo"
        self.reset()

    # ------------------------------------------------------------ save
    def load_best(self):
        try:
            with open(SAVE_FILE) as f:
                return json.load(f).get("best")
        except Exception:
            return None

    def save_best(self):
        try:
            with open(SAVE_FILE, "w") as f:
                json.dump({"best": self.best}, f)
        except Exception:
            pass

    # ------------------------------------------------------------ state
    def reset(self):
        self.x, self.y = center_x(0), 0.0
        self.vx, self.vy = 0.0, -60.0
        self.ang, self.spin = 0.0, 0.0
        self.t = 0.0
        self.time = 0.0
        self.falls = 0
        self.checkpoint = 0
        self.falling = 0.0
        self.hit_cd = 0.0
        self.particles = []
        self.obstacles = build_obstacles()
        self.cam = Camera()
        self.cam.x, self.cam.y = self.x, self.y - H * 0.18
        self.countdown = 3.0
        for s in self.seats:
            s.gas, s.empty = 100.0, False
        self.flash = ""
        self.flash_t = 0.0

    def seat_dir(self, i):
        a = self.ang + i * math.pi / 2 - math.pi / 2
        return math.cos(a), math.sin(a)

    # ------------------------------------------------------------ input
    def wanted_farts(self, keys):
        if self.mode == "coop":
            return [keys[s.key] for s in self.seats]
        dx = (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a])
        dy = (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
        if not dx and not dy:
            return [False] * 4
        ln = math.hypot(dx, dy)
        dx, dy = dx / ln, dy / ln
        res = []
        for i in range(4):
            sx, sy = self.seat_dir(i)
            # gas pushes the raft away from the animal: thrust = -seat_dir
            res.append(-sx * dx - sy * dy > 0.38)
        return res

    # ------------------------------------------------------------ update
    def update(self, dt, keys):
        self.t += dt
        if self.flash_t > 0:
            self.flash_t -= dt
        self.update_particles(dt)
        if self.state != "play":
            for s in self.seats:
                self.stop_sound(s)
            return
        if self.countdown > 0:
            self.countdown -= dt
            self.cam.follow(self.x, self.y, dt)
            return
        self.time += dt

        if self.falling > 0:
            self.falling -= dt
            if self.falling <= 0:
                self.respawn()
            self.cam.follow(self.x, self.y, dt)
            return

        s = -self.y
        fx, fy = flow_dir(s)
        current = 230 + 60 * min(1, s / 6000)
        ax = (fx * current - self.vx) * 0.9
        ay = (fy * current - self.vy) * 0.9

        want = self.wanted_farts(keys)
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
                bx, by = self.x + sx * RAFT_R, self.y + sy * RAFT_R
                for _ in range(3):
                    sp = random.uniform(150, 320)
                    a = math.atan2(sy, sx) + random.uniform(-0.5, 0.5)
                    self.particles.append(Particle(bx, by, math.cos(a) * sp + self.vx * 0.5,
                                                   math.sin(a) * sp + self.vy * 0.5,
                                                   random.uniform(0.4, 0.9), random.uniform(8, 16)))
                self.play_sound(seat)
            else:
                seat.gas = min(100, seat.gas + 22 * dt)
                if seat.empty and seat.gas > 30:
                    seat.empty = False
                self.stop_sound(seat)

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
                self.start_fall()

        if self.hit_cd > 0:
            self.hit_cd -= dt
        for ob in self.obstacles:
            if abs(ob.s - s) > 400:
                continue
            ox, oy, r = ob.collide(self.t, (self.x, self.y))
            dx, dy = self.x - ox, self.y - oy
            d = math.hypot(dx, dy)
            if d < r + RAFT_R and d > 0.01:
                nx, ny = dx / d, dy / d
                self.x, self.y = ox + nx * (r + RAFT_R), oy + ny * (r + RAFT_R)
                if self.hit_cd <= 0:
                    self.vx += nx * 650
                    self.vy += ny * 650
                    self.spin += random.choice([-1, 1]) * 4
                    self.cam.shake = 10
                    self.hit_cd = 0.35

        cp = int(max(0, s) // CHECKPOINT_STEP) * CHECKPOINT_STEP
        if cp > self.checkpoint:
            self.checkpoint = cp
            self.say("Чекпоинт!")
        if s >= TRACK_LEN:
            self.finish()
        self.cam.follow(self.x, self.y, dt)

    def update_particles(self, dt):
        alive = []
        for p in self.particles:
            p.life -= dt
            if p.life > 0:
                p.x += p.vx * dt
                p.y += p.vy * dt
                p.vx *= 1 - 2.5 * dt
                p.vy *= 1 - 2.5 * dt
                p.r += 18 * dt
                alive.append(p)
        self.particles = alive[-600:]

    def play_sound(self, seat):
        if not self.audio or seat.sound is None:
            return
        if seat.channel is None or not seat.channel.get_busy():
            seat.channel = seat.sound.play()

    def stop_sound(self, seat):
        seat.farting = False

    def say(self, text):
        self.flash, self.flash_t = text, 1.4

    def start_fall(self):
        self.falling = 1.0
        self.falls += 1
        self.say("Плюх! +3 сек")
        self.time += 3

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
            self.save_best()

    # ------------------------------------------------------------ draw
    def draw(self):
        surf = self.screen
        surf.fill(CLIFF)
        self.draw_track(surf)
        for ob in self.obstacles:
            if abs(ob.s + self.cam.y) < H + 300:
                ob.draw(surf, self.cam, self.t)
        self.draw_finish(surf)
        self.draw_particles(surf, behind=True)
        self.draw_raft(surf)
        self.draw_hud(surf)
        if self.state == "menu":
            self.draw_menu(surf)
        elif self.state == "finish":
            self.draw_finish_screen(surf)
        elif self.state == "pause":
            self.overlay(surf, ["Пауза", "", "Esc — продолжить", "R — заново", "Q — в меню"])

    def edge_points(self):
        top = self.cam.y - H / 2 - 80
        bot = self.cam.y + H / 2 + 80
        pts = []
        y = bot
        while y > top:
            s = -y
            pts.append((s, center_x(s), half_width(s), y))
            y -= 14
        return pts

    def draw_track(self, surf):
        pts = self.edge_points()
        if len(pts) < 2:
            return
        cam = self.cam
        # cliff shadows under open edges
        for i in range(len(pts) - 1):
            s, cx, hw, y = pts[i]
            s2, cx2, hw2, y2 = pts[i + 1]
            for side in (-1, 1):
                a = cam.to_screen(cx + side * hw, y)
                b = cam.to_screen(cx2 + side * hw2, y2)
                c = cam.to_screen(cx2 + side * (hw2 + 70), y2 + 40)
                d = cam.to_screen(cx + side * (hw + 70), y + 40)
                pygame.draw.polygon(surf, CLIFF_DARK, [a, b, c, d])
        left = [cam.to_screen(cx - hw, y) for s, cx, hw, y in pts]
        right = [cam.to_screen(cx + hw, y) for s, cx, hw, y in pts]
        pygame.draw.polygon(surf, WATER, left + right[::-1])
        # flow lines
        for lane in range(-3, 4):
            k = lane / 3.6
            for i in range(0, len(pts) - 1):
                s, cx, hw, y = pts[i]
                phase = (s + self.t * 260 + lane * 97) % 220
                if phase < 90:
                    s2, cx2, hw2, y2 = pts[i + 1]
                    a = cam.to_screen(cx + hw * k, y)
                    b = cam.to_screen(cx2 + hw2 * k, y2)
                    pygame.draw.line(surf, WATER_LIGHT, a, b, 3)
        # rails
        for i in range(len(pts) - 1):
            s, cx, hw, y = pts[i]
            s2, cx2, hw2, y2 = pts[i + 1]
            for side in (-1, 1):
                a = cam.to_screen(cx + side * hw, y)
                b = cam.to_screen(cx2 + side * hw2, y2)
                if has_rail(s):
                    pygame.draw.line(surf, RAIL_DARK, (a[0], a[1] + 6), (b[0], b[1] + 6), 16)
                    pygame.draw.line(surf, RAIL, a, b, 14)
                else:
                    pygame.draw.line(surf, (230, 245, 255), a, b, 4)
        # checkpoints
        for cp in range(CHECKPOINT_STEP, TRACK_LEN, CHECKPOINT_STEP):
            if abs(-cp - cam.y) < H:
                cx, hw = center_x(cp), half_width(cp)
                a = cam.to_screen(cx - hw, -cp)
                b = cam.to_screen(cx + hw, -cp)
                col = (255, 230, 90) if cp <= self.checkpoint else (255, 255, 255)
                for k in range(0, 20, 2):
                    p = (a[0] + (b[0] - a[0]) * k / 20, a[1])
                    q = (a[0] + (b[0] - a[0]) * (k + 1) / 20, a[1])
                    pygame.draw.line(surf, col, p, q, 5)

    def draw_finish(self, surf):
        s = TRACK_LEN
        if abs(-s - self.cam.y) > H:
            return
        cx, hw = center_x(s), half_width(s)
        a = self.cam.to_screen(cx - hw - 20, -s)
        b = self.cam.to_screen(cx + hw + 20, -s)
        sq = 30
        n = int((b[0] - a[0]) / sq)
        for i in range(n):
            for j in range(2):
                col = WHITE if (i + j) % 2 == 0 else BLACK
                pygame.draw.rect(surf, col, (a[0] + i * sq, a[1] + j * sq - sq, sq, sq))
        pygame.draw.rect(surf, (200, 150, 60), (a[0] - 20, a[1] - 140, 30, 170))
        pygame.draw.rect(surf, (200, 150, 60), (b[0] - 10, b[1] - 140, 30, 170))
        banner = pygame.Rect(a[0], a[1] - 150, b[0] - a[0], 56)
        pygame.draw.rect(surf, (230, 180, 60), banner, border_radius=8)
        txt = self.mid.render("FINISH", True, (190, 40, 50))
        surf.blit(txt, txt.get_rect(center=banner.center))

    def draw_particles(self, surf, behind):
        for p in self.particles:
            k = p.life / p.max
            fade = (190, 235, 160)
            col = tuple(int(GAS[i] * k + fade[i] * (1 - k)) for i in range(3))
            pygame.draw.circle(surf, col, self.cam.to_screen(p.x, p.y), int(p.r))

    def draw_raft(self, surf):
        scale = 1.0
        if self.falling > 0:
            scale = max(0.05, self.falling)
        c = self.cam.to_screen(self.x, self.y)
        R = int(RAFT_R * scale)
        pygame.draw.circle(surf, (20, 90, 160), (c[0], c[1] + 10), R + 6)
        pygame.draw.circle(surf, RAFT_RING, c, R + 6)
        pygame.draw.circle(surf, RAFT_FLOOR, c, int(R * 0.78))
        for k in range(-2, 3):
            a = self.ang + math.pi / 4
            ox, oy = math.cos(a) * k * R * 0.28, math.sin(a) * k * R * 0.28
            dx, dy = -math.sin(a) * R * 0.7, math.cos(a) * R * 0.7
            pygame.draw.line(surf, (95, 150, 60), (c[0] + ox - dx, c[1] + oy - dy), (c[0] + ox + dx, c[1] + oy + dy), 2)
        for i in range(4):
            a = self.ang + i * math.pi / 2 + math.pi / 4
            hx, hy = c[0] + math.cos(a) * (R + 3), c[1] + math.sin(a) * (R + 3)
            pygame.draw.circle(surf, (180, 70, 60), (int(hx), int(hy)), max(2, int(8 * scale)))
        for i, seat in enumerate(self.seats):
            sx, sy = self.seat_dir(i)
            px, py = c[0] + sx * R * 0.72, c[1] + sy * R * 0.72
            self.draw_animal(surf, seat, px, py, math.atan2(-sy, -sx), scale)

    def draw_animal(self, surf, seat, x, y, face, scale):
        r = 22 * scale
        if seat.farting:
            r *= 1 + 0.08 * math.sin(self.t * 40)
        fx, fy = math.cos(face), math.sin(face)
        px, py = -fy, fx
        x, y = int(x), int(y)
        if seat.kind == "bear":
            for s in (-1, 1):
                pygame.draw.circle(surf, seat.color, (int(x + fx * r * 0.5 + px * s * r * 0.7), int(y + fy * r * 0.5 + py * s * r * 0.7)), int(r * 0.4))
        if seat.kind == "monkey":
            for s in (-1, 1):
                pygame.draw.circle(surf, seat.belly, (int(x + px * s * r), int(y + py * s * r)), int(r * 0.35))
        pygame.draw.circle(surf, seat.color, (x, y), int(r))
        hx, hy = x + fx * r * 0.45, y + fy * r * 0.45
        if seat.kind == "frog":
            for s in (-1, 1):
                ex, ey = int(hx + px * s * r * 0.45), int(hy + py * s * r * 0.45)
                pygame.draw.circle(surf, seat.color, (ex, ey), int(r * 0.35))
                pygame.draw.circle(surf, WHITE, (ex, ey), int(r * 0.22))
                pygame.draw.circle(surf, BLACK, (int(ex + fx * 2), int(ey + fy * 2)), max(1, int(r * 0.1)))
        else:
            pygame.draw.circle(surf, seat.belly, (int(hx + fx * r * 0.2), int(hy + fy * r * 0.2)), int(r * 0.42))
            for s in (-1, 1):
                ex, ey = int(hx + px * s * r * 0.3 - fx * r * 0.1), int(hy + py * s * r * 0.3 - fy * r * 0.1)
                pygame.draw.circle(surf, WHITE, (ex, ey), max(1, int(r * 0.15)))
                pygame.draw.circle(surf, BLACK, (ex, ey), max(1, int(r * 0.08)))
        if scale > 0.6:
            lbl = self.small.render(seat.name, True, WHITE)
            surf.blit(lbl, lbl.get_rect(center=(int(x - fx * 30), int(y - fy * 30))))

    def draw_hud(self, surf):
        t = self.time
        txt = self.mid.render(f"{int(t // 60):02d}:{t % 60:05.2f}", True, WHITE)
        box = txt.get_rect(center=(W / 2, 28)).inflate(30, 10)
        pygame.draw.rect(surf, (30, 60, 110), box, border_radius=12)
        surf.blit(txt, txt.get_rect(center=box.center))
        # progress
        prog = max(0, min(1, -self.y / TRACK_LEN))
        bar = pygame.Rect(W - 34, 80, 14, H - 200)
        pygame.draw.rect(surf, (30, 60, 110), bar, border_radius=7)
        fill = bar.copy()
        fill.height = int(bar.height * prog)
        fill.bottom = bar.bottom
        pygame.draw.rect(surf, GAS, fill, border_radius=7)
        # gas bars
        for i, seat in enumerate(self.seats):
            x = 20 + i * 180
            y = H - 50
            pygame.draw.rect(surf, (30, 60, 110), (x, y, 165, 36), border_radius=10)
            pygame.draw.circle(surf, seat.color, (x + 18, y + 18), 12)
            key = seat.label if self.mode == "coop" else ""
            lbl = self.font.render(f"{seat.name} {key}", True, WHITE)
            surf.blit(lbl, (x + 36, y + 2))
            g = pygame.Rect(x + 36, y + 24, 120, 7)
            pygame.draw.rect(surf, (15, 30, 60), g, border_radius=3)
            g2 = g.copy()
            g2.width = int(g.width * seat.gas / 100)
            pygame.draw.rect(surf, (220, 80, 60) if seat.empty else GAS, g2, border_radius=3)
        if self.flash_t > 0:
            t = self.mid.render(self.flash, True, WHITE)
            surf.blit(t, t.get_rect(center=(W / 2, 90)))
        if self.state == "play" and self.countdown > 0:
            n = int(math.ceil(self.countdown))
            t = self.big.render(str(n), True, WHITE)
            surf.blit(t, t.get_rect(center=(W / 2, H / 2 - 120)))

    def overlay(self, surf, lines):
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((10, 20, 50, 170))
        surf.blit(shade, (0, 0))
        y = H / 2 - len(lines) * 22
        for i, line in enumerate(lines):
            f = self.big if i == 0 else self.font
            t = f.render(line, True, WHITE)
            surf.blit(t, t.get_rect(center=(W / 2, y)))
            y += 80 if i == 0 else 30

    def draw_menu(self, surf):
        best = f"Рекорд: {int(self.best // 60):02d}:{self.best % 60:05.2f}" if self.best else "Рекорда пока нет"
        self.overlay(surf, [
            "FART TOGETHER",
            "Плот двигается только газом: зверь пукает — плот летит от него.",
            "Не вылетай с горки там, где нет бортиков. Уворачивайся от молотов, крутилок и мин.",
            "",
            "1 — Соло: стрелки / WASD (нужные звери пукают сами)",
            "2 — Вместе на одной клавиатуре: Лягуха Q, Мишаня P, Бегемот Z, Мартын M",
            "",
            best,
            "Esc — пауза / выход",
        ])

    def draw_finish_screen(self, surf):
        t = self.time
        lines = ["ФИНИШ!", f"Время: {int(t // 60):02d}:{t % 60:05.2f}", f"Падений: {self.falls}"]
        if self.new_record:
            lines.append("Новый рекорд!")
        lines += ["", "Enter — ещё раз", "Esc — в меню"]
        self.overlay(surf, lines)

    # ------------------------------------------------------------ events
    def handle(self, ev):
        if ev.type != pygame.KEYDOWN:
            return True
        if self.state == "menu":
            if ev.key in (pygame.K_1, pygame.K_KP1):
                self.mode = "solo"
                self.reset()
                self.state = "play"
            elif ev.key in (pygame.K_2, pygame.K_KP2):
                self.mode = "coop"
                self.reset()
                self.state = "play"
            elif ev.key == pygame.K_ESCAPE:
                return False
        elif self.state == "play":
            if ev.key == pygame.K_ESCAPE:
                self.state = "pause"
        elif self.state == "pause":
            if ev.key == pygame.K_ESCAPE:
                self.state = "play"
            elif ev.key == pygame.K_r:
                self.reset()
                self.state = "play"
            elif ev.key == pygame.K_q:
                self.reset()
                self.state = "menu"
        elif self.state == "finish":
            if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.reset()
                self.state = "play"
            elif ev.key == pygame.K_ESCAPE:
                self.reset()
                self.state = "menu"
        return True


def main():
    try:
        pygame.mixer.pre_init(22050, -16, 2, 512)
    except Exception:
        pass
    pygame.init()
    try:
        pygame.mixer.init()
        pygame.mixer.set_num_channels(16)
    except Exception:
        pass
    pygame.display.set_caption("Fart Together")
    screen = pygame.display.set_mode((W, H))
    clock = pygame.time.Clock()
    game = Game(screen)
    frames = int(os.environ.get("FT_TEST_FRAMES", "0"))
    n = 0
    running = True
    while running:
        dt = min(clock.tick(FPS) / 1000.0, 1 / 30)
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif not game.handle(ev):
                running = False
        game.update(dt, pygame.key.get_pressed())
        game.draw()
        pygame.display.flip()
        n += 1
        if frames and n >= frames:
            running = False
    pygame.quit()


if __name__ == "__main__":
    main()
    sys.exit(0)
