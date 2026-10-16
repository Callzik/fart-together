"""Fart Together — кооперативная гонка на надувном плоту (3D, Panda3D).

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
import tempfile
import time
import wave

from panda3d.core import (AmbientLight, AntialiasAttrib, DirectionalLight, Filename, Fog,
                          KeyboardButton, PNMImage, TextNode, Texture, TextureStage,
                          TransparencyAttrib, Vec3, Vec4, loadPrcFileData)

loadPrcFileData("", """
window-title Fart Together
win-size 1280 720
framebuffer-multisample 1
multisamples 4
sync-video 1
""")

from direct.gui.DirectGui import DirectFrame  # noqa: E402
from direct.gui.OnscreenText import OnscreenText  # noqa: E402
from direct.showbase.ShowBase import ShowBase  # noqa: E402

import gfx  # noqa: E402
import net  # noqa: E402
import sim  # noqa: E402
from gfx import U, to3d  # noqa: E402

if getattr(sys, "frozen", False):
    HERE = os.path.dirname(sys.executable)
else:
    HERE = os.path.dirname(os.path.abspath(__file__))
SAVE_FILE = os.path.join(os.path.expanduser("~"), ".fart_together.json")
SEAT_R = 0.64


def asset(name):
    return Filename.from_os_specific(os.path.join(HERE, "assets", name)).get_fullpath()


# ---------------------------------------------------------------- sound
def write_wav(path, samples, rate=22050):
    buf = array.array("h", (int(max(-1, min(1, v)) * 32000) for v in samples))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(buf.tobytes())


def fart_samples(seed, rate=22050):
    rnd = random.Random(seed)
    dur = 0.35 + rnd.random() * 0.25
    base = 70 + rnd.random() * 60
    phase = 0.0
    for i in range(int(rate * dur)):
        t = i / rate
        f = base * (1 + 0.35 * math.sin(t * 38 + seed)) * (1 - 0.3 * t / dur)
        phase += f / rate
        v = (1.0 if (phase % 1.0) < 0.35 else -0.6) + rnd.uniform(-0.5, 0.5)
        yield v * min(1.0, t * 40) * (1 - t / dur) ** 1.5 * 0.5


def bonk_samples(rate=22050):
    for i in range(int(rate * 0.25)):
        t = i / rate
        yield 0.6 * math.sin(2 * math.pi * (220 - 300 * t) * t) * (1 - t / 0.25) ** 2


def clock_texture():
    img = PNMImage(64, 64, 4)
    img.fill(1, 1, 1)
    img.alpha_fill(0)
    for y in range(64):
        for x in range(64):
            d = math.hypot(x - 31.5, y - 31.5)
            if d < 28:
                img.set_alpha(x, y, 1)
                ring = d > 22
                hand = (abs(x - 31.5) < 2.5 and 12 < y < 33) or (abs(y - 31.5) < 2.5 and 30 < x < 46)
                if not ring and not hand:
                    img.set_xel(x, y, 0.25, 0.3, 0.4)
    tex = Texture("clock")
    tex.load(img)
    return tex


class Puff:
    __slots__ = ("np", "pos", "vel", "life", "max", "size")


class FartApp(ShowBase):
    def __init__(self, test_keys=None):
        ShowBase.__init__(self)
        self.disable_mouse()
        self.test_keys = test_keys
        self.set_background_color(*gfx.C_SKY)
        self.render.set_antialias(AntialiasAttrib.M_multisample)
        self.render.set_two_sided(True)
        try:
            self.font = self.loader.load_font(asset("DejaVuSans-Bold.ttf"))
            self.font.set_pixels_per_unit(80)
        except Exception:
            self.font = None

        self.world = sim.World()
        self.world.best = self.load_best()
        self.mode = "solo"
        self.net = None
        self.my_seat = 0
        self.ip_text = ""
        self.net_msg = ""
        self.ips = []
        self.shake = 0.0
        self.cam_pos = None

        self.setup_scene()
        self.setup_sounds()
        self.setup_hud()
        self.setup_input()
        self.task_mgr.add(self.loop, "loop")

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
                json.dump({"best": self.world.best}, f)
        except Exception:
            pass

    # ------------------------------------------------------------ scene
    def setup_scene(self):
        P = self.protos = gfx.Protos()
        amb = AmbientLight("amb")
        amb.set_color(Vec4(0.68, 0.70, 0.76, 1))
        sun = DirectionalLight("sun")
        sun.set_color(Vec4(0.72, 0.70, 0.62, 1))
        sun_np = self.render.attach_new_node(sun)
        sun_np.set_hpr(35, -55, 0)
        self.render.set_light(self.render.attach_new_node(amb))
        self.render.set_light(sun_np)
        fog = Fog("fog")
        fog.set_color(*gfx.C_SKY[:3])
        fog.set_linear_range(28, 80)
        self.render.set_fog(fog)

        self.static = self.render.attach_new_node("static")
        self.water = gfx.build_track(self.static)
        self.water.set_light_off()
        gfx.build_scenery(self.static)
        gfx.build_finish(self.static, P, self.font)
        self.checkpoints = {}
        for cp in range(sim.CHECKPOINT_STEP, sim.TRACK_LEN, sim.CHECKPOINT_STEP):
            self.checkpoints[cp] = gfx.build_checkpoint(self.static, P, cp)

        self.obs_nodes = []
        for ob in self.world.obstacles:
            if ob.kind == "hammer":
                root, pivot, L = gfx.build_hammer(self.static, P, ob)
                self.obs_nodes.append((ob, root, pivot, L))
            elif ob.kind == "spinner":
                root, rot = gfx.build_spinner(self.static, P, ob)
                self.obs_nodes.append((ob, root, rot, None))
            else:
                self.obs_nodes.append((ob, gfx.build_mine(self.render, P), None, None))

        self.raft = gfx.build_raft(self.render, P)
        self.raft.set_scale(1.15)
        self.animals = []
        for seat in self.world.seats:
            a = gfx.build_animal(self.render, P, seat.kind)
            a.set_scale(1.2)
            tn = TextNode("name")
            tn.set_text(seat.name)
            if self.font:
                tn.set_font(self.font)
            tn.set_align(TextNode.A_center)
            tn.set_text_color(1, 1, 1, 1)
            tn.set_shadow(0.06, 0.06)
            tn.set_shadow_color(0.1, 0.15, 0.25, 0.9)
            lbl = self.render.attach_new_node(tn)
            lbl.set_scale(0.12)
            lbl.set_billboard_point_eye()
            lbl.set_light_off()
            lbl.set_fog_off()
            lbl.set_depth_test(False)
            lbl.set_depth_write(False)
            lbl.set_bin("fixed", 10)
            self.animals.append((a, lbl))

        self.puffs, self.puff_pool = [], []
        for _ in range(260):
            np_ = P.sphere.copy_to(self.render)
            np_.set_transparency(TransparencyAttrib.M_alpha)
            np_.set_light_off()
            np_.set_depth_write(False)
            np_.set_bin("transparent", 0)
            np_.hide()
            self.puff_pool.append(np_)
        self.rings, self.ring_pool = [], []
        ring_proto = gfx.torus(1.0, 0.05, 28, 4, (1, 1, 1, 1))
        for _ in range(24):
            r = ring_proto.copy_to(self.render)
            r.set_transparency(TransparencyAttrib.M_alpha)
            r.set_light_off()
            r.set_depth_write(False)
            r.set_bin("transparent", 0)
            r.hide()
            self.ring_pool.append(r)
        self.ring_timer = 0.0

    def setup_sounds(self):
        self.sfx, self.bonk = [], None
        try:
            d = tempfile.mkdtemp(prefix="fart_together_")
            for i in range(4):
                p = os.path.join(d, f"fart{i}.wav")
                write_wav(p, list(fart_samples(i)))
                self.sfx.append(self.loader.load_sfx(Filename.from_os_specific(p).get_fullpath()))
            p = os.path.join(d, "bonk.wav")
            write_wav(p, list(bonk_samples()))
            self.bonk = self.loader.load_sfx(Filename.from_os_specific(p).get_fullpath())
        except Exception:
            self.sfx = []

    # ------------------------------------------------------------ HUD
    def text(self, txt="", pos=(0, 0), scale=0.06, parent=None, align=TextNode.A_center):
        return OnscreenText(text=txt, pos=pos, scale=scale, fg=(1, 1, 1, 1), shadow=(0.05, 0.1, 0.2, 0.8),
                            align=align, font=self.font, parent=parent or self.aspect2d, mayChange=True)

    def setup_hud(self):
        self.timer_frame = DirectFrame(frameColor=(0.12, 0.18, 0.28, 0.55), frameSize=(-0.27, 0.27, -0.055, 0.055),
                                       pos=(0, 0, 0.9), parent=self.aspect2d)
        clock = DirectFrame(image=clock_texture(), image_scale=0.035, frameColor=(0, 0, 0, 0),
                            pos=(-0.2, 0, 0), parent=self.timer_frame)
        clock.set_transparency(TransparencyAttrib.M_alpha)
        self.timer_text = self.text("00:00.00", (0.04, -0.022), 0.06, self.timer_frame)
        self.flash_text = self.text("", (0, 0.72), 0.08)
        self.count_text = self.text("", (0, 0.3), 0.25)
        self.hint_text = self.text("", (0, -0.79), 0.045)

        self.gas_bars = []
        for i, seat in enumerate(self.world.seats):
            fr = DirectFrame(frameColor=(0.12, 0.18, 0.28, 0.6), frameSize=(-0.25, 0.25, -0.05, 0.05),
                             pos=(-0.84 + i * 0.56, 0, -0.9), parent=self.aspect2d)
            label = self.text(seat.name, (-0.22, 0.005), 0.042, fr, TextNode.A_left)
            DirectFrame(frameColor=(0.05, 0.08, 0.15, 0.9), frameSize=(-0.22, 0.22, -0.035, -0.015), parent=fr)
            bar = DirectFrame(frameColor=gfx.C_GAS, frameSize=(0, 0.44, -0.035, -0.015), pos=(-0.22, 0, 0), parent=fr)
            self.gas_bars.append((fr, label, bar))

        self.prog_back = DirectFrame(frameColor=(0.12, 0.18, 0.28, 0.55), frameSize=(-0.012, 0.012, -0.6, 0.6),
                                     pos=(-0.06, 0, 0.05), parent=self.a2dRightCenter)
        self.prog_bar = DirectFrame(frameColor=gfx.C_GAS, frameSize=(-0.012, 0.012, 0, 1.2),
                                    pos=(0, 0, -0.6), parent=self.prog_back)

        self.overlay = DirectFrame(frameColor=(0.05, 0.1, 0.22, 0.72), frameSize=(-3, 3, -1, 1), parent=self.aspect2d)
        self.ov_title = self.text("", (0, 0.55), 0.13, self.overlay)
        self.ov_lines = [self.text("", (0, 0.35 - i * 0.085), 0.05, self.overlay) for i in range(10)]

    def show_overlay(self, title, lines):
        self.overlay.show()
        self.ov_title.setText(title)
        for i, t in enumerate(self.ov_lines):
            t.setText(lines[i] if i < len(lines) else "")

    @staticmethod
    def fmt(t):
        return f"{int(t // 60):02d}:{t % 60:05.2f}"

    def update_hud(self):
        w = self.world
        self.timer_text.setText(self.fmt(w.time))
        self.flash_text.setText(w.flash if w.flash_t > 0 else "")
        self.count_text.setText(str(int(math.ceil(w.countdown))) if w.state == "play" and w.countdown > 0 else "")
        prog = max(0.001, min(1, -w.y / sim.TRACK_LEN))
        self.prog_bar["frameSize"] = (-0.012, 0.012, 0, 1.2 * prog)
        online = self.mode in ("host", "client")
        players = self.players()
        for i, (fr, label, bar) in enumerate(self.gas_bars):
            seat = w.seats[i]
            suffix = ""
            if self.mode == "coop":
                suffix = f"  [{seat.key.upper()}]"
            elif online:
                suffix = "  (ты)" if i == self.my_seat else ("" if i in players else "  —")
            label.setText(seat.name + suffix)
            bar["frameSize"] = (0, 0.44 * max(0.001, seat.gas) / 100, -0.035, -0.015)
            bar["frameColor"] = (0.9, 0.3, 0.25, 1) if seat.empty else gfx.C_GAS
            fr["frameColor"] = (0.30, 0.45, 0.15, 0.75) if online and i == self.my_seat else (0.12, 0.18, 0.28, 0.6)
        self.hint_text.setText("Пробел — пукать" if online and w.state == "play" else "")

        st = w.state
        if st == "menu":
            best = f"Рекорд: {self.fmt(w.best)}" if w.best else "Рекорда пока нет"
            self.show_overlay("FART TOGETHER", [
                "Плот двигается только газом: зверь пукает, и плот летит от него.",
                "Не вылетай с горки там, где нет бортиков. Уворачивайся от молотов, крутилок и мин.",
                "",
                "1   Соло: стрелки / WASD (нужные звери пукают сами)",
                "2   Вместе за одной клавиатурой: Q, P, Z, M",
                "3   Онлайн: создать игру",
                "4   Онлайн: подключиться",
                "",
                best,
                self.net_msg or "Esc — выход",
            ])
        elif st == "pause":
            self.show_overlay("Пауза", ["", "Esc — продолжить", "R — заново", "Q — в меню"])
        elif st == "lobby":
            names = ", ".join(w.seats[i].name for i in self.net.seats_taken())
            self.show_overlay("Онлайн: ты хост", [
                "Друзья выбирают «Подключиться» и вводят один из адресов:",
                "   ".join(f"{ip}:{net.PORT}" for ip in self.ips),
                "Через интернет: Radmin VPN / ZeroTier / playit.gg (см. README)",
                "",
                f"Игроки ({len(self.net.seats_taken())}/4): {names}",
                "",
                "Enter — старт, Esc — отмена",
            ])
        elif st == "join":
            cursor = "_" if int(time.monotonic() * 2) % 2 else " "
            self.show_overlay("Подключиться", [
                "Введи адрес хоста (например 192.168.1.5 или 26.10.20.30:5555):",
                "",
                self.ip_text + cursor,
                "",
                "Enter — подключиться, Esc — назад",
            ])
        elif st == "joining":
            c = self.net
            line = "Подключаюсь..." if c.seat is None else f"Ты — {w.seats[c.seat].name}. Ждём, пока хост нажмёт старт"
            self.show_overlay("Онлайн", [line, "", "Esc — выйти"])
        elif st == "finish":
            lines = [f"Время: {self.fmt(w.time)}", f"Падений: {w.falls}"]
            if w.new_record:
                lines.append("Новый рекорд!")
            lines.append("")
            if self.mode == "client":
                lines += ["Ждём, пока хост начнёт заново", "Esc — выйти"]
            else:
                lines += ["Enter — ещё раз", "Esc — в меню"]
            self.show_overlay("ФИНИШ!", lines)
        else:
            self.overlay.hide()

    # ------------------------------------------------------------ input
    def setup_input(self):
        self.accept("keystroke", self.on_char)
        for key in ("escape", "enter", "backspace", "1", "2", "3", "4", "r", "q"):
            self.accept(key, self.on_key, [key])

    def down(self, name):
        if self.test_keys is not None:
            return name in self.test_keys
        mw = self.mouseWatcherNode
        if mw is None:
            return False
        btn = {"left": KeyboardButton.left(), "right": KeyboardButton.right(), "up": KeyboardButton.up(),
               "down": KeyboardButton.down(), "space": KeyboardButton.space()}.get(name)
        return mw.is_button_down(btn or KeyboardButton.ascii_key(name))

    def players(self):
        if self.mode == "host" and self.net:
            return self.net.seats_taken()
        if self.mode == "client" and self.net and self.net.state:
            return self.net.state.get("pl", [])
        return [0, 1, 2, 3]

    def local_fart(self):
        return self.down("space") or self.down(self.world.seats[self.my_seat].key)

    def wanted(self):
        w = self.world
        if self.mode == "host":
            res = [bool(v) for v in self.net.inputs]
            res[0] = self.local_fart()
            return res
        if self.mode == "coop":
            return [self.down(s.key) for s in w.seats]
        dx = (self.down("right") or self.down("d")) - (self.down("left") or self.down("a"))
        dy = (self.down("down") or self.down("s")) - (self.down("up") or self.down("w"))
        return w.auto_farts(dx, dy)

    def on_char(self, ch):
        if self.world.state == "join" and (ch.isalnum() or ch in ".:-"):
            self.ip_text = (self.ip_text + ch)[:60]

    def start(self, mode):
        self.mode = mode
        self.world.reset()
        self.world.state = "play"
        self.clear_fx()

    def on_key(self, key):
        w = self.world
        st = w.state
        if self.mode == "client":
            if key == "escape":
                self.leave_online()
            return
        if st == "join":
            if key == "backspace":
                self.ip_text = self.ip_text[:-1]
            elif key == "enter" and self.ip_text.strip():
                self.start_join()
            elif key == "escape":
                w.state = "menu"
        elif st == "lobby":
            if key == "enter":
                self.start("host")
            elif key == "escape":
                self.leave_online()
        elif st == "menu":
            if key == "1":
                self.start("solo")
            elif key == "2":
                self.start("coop")
            elif key == "3":
                self.start_host()
            elif key == "4":
                w.state = "join"
            elif key == "escape":
                self.user_exit()
        elif st == "play":
            if key == "escape":
                if self.mode == "host":
                    self.leave_online()
                else:
                    w.state = "pause"
        elif st == "pause":
            if key == "escape":
                w.state = "play"
            elif key == "r":
                self.start(self.mode)
            elif key == "q":
                w.reset()
                w.state = "menu"
        elif st == "finish":
            if key == "enter":
                self.start(self.mode)
            elif key == "escape":
                if self.mode == "host":
                    self.leave_online()
                else:
                    w.reset()
                    w.state = "menu"

    # ------------------------------------------------------------ online
    def start_host(self):
        try:
            self.net = net.Host()
        except OSError as e:
            self.net_msg = f"Не удалось открыть порт {net.PORT}: {e}"
            return
        self.mode, self.my_seat, self.net_msg = "host", 0, ""
        self.ips = net.local_ips()
        self.world.reset()
        self.world.state = "lobby"

    def start_join(self):
        self.net = net.Client(self.ip_text)
        self.mode, self.net_msg = "client", ""
        self.world.reset()
        self.world.state = "joining"

    def leave_online(self, msg=""):
        if self.net:
            self.net.close()
        self.net = None
        self.mode, self.my_seat = "solo", 0
        self.net_msg = msg
        self.world.reset()
        self.world.state = "menu"

    # ------------------------------------------------------------ frame
    def loop(self, task):
        self.tick(min(globalClock.get_dt(), 1 / 30))  # noqa: F821
        return task.cont

    def tick(self, dt):
        w = self.world
        if self.mode == "client":
            c = self.net
            if c.error:
                self.leave_online(c.error)
            else:
                if c.seat is not None:
                    self.my_seat = c.seat
                if c.state is not None:
                    w.apply_snapshot(c.state, min(0.25, time.monotonic() - c.state_time), dt)
                    if w.state == "lobby":
                        w.state = "joining"
                c.send_input(self.local_fart() if w.state == "play" else False)
        else:
            was = w.state
            w.update(dt, self.wanted())
            if was == "play" and w.state == "finish" and w.new_record:
                self.save_best()
            if self.mode == "host" and self.net:
                self.net.broadcast(w.snapshot(self.net.seats_taken()))
        self.update_scene(dt)
        self.update_hud()

    def clear_fx(self):
        for p in self.puffs:
            p.np.hide()
            self.puff_pool.append(p.np)
        self.puffs = []
        for r in self.rings:
            r[0].hide()
            self.ring_pool.append(r[0])
        self.rings = []

    def raft_pos(self):
        w = self.world
        p = to3d(w.x, w.y, 0.04 + 0.03 * math.sin(w.t * 3.1))
        if w.falling > 0:
            k = 1.2 - w.falling
            p += Vec3(w.fall_dir * k * 2.5, k * 1.5, -9 * k * k)
        return p

    def update_scene(self, dt):
        w = self.world
        t = w.t
        here = -w.y
        for ob, root, mover, L in self.obs_nodes:
            if abs(ob.s - here) > 8000:
                continue
            if ob.kind == "hammer":
                d = (ob.head(t)[0] - sim.center_x(ob.s)) / U
                mover.set_r(-math.degrees(math.asin(max(-0.99, min(0.99, d / L)))))
            elif ob.kind == "spinner":
                mover.set_h(-math.degrees(ob.angle(t)))
            else:
                x, y = ob.pos(t)
                root.set_pos(to3d(x, y, 0.02 + 0.04 * math.sin(t * 2.5 + ob.phase)))
                root.set_h(t * 20)
        for cp, (root, parts) in self.checkpoints.items():
            col = (1.0, 0.85, 0.25, 1) if cp <= w.checkpoint else (1, 1, 1, 1)
            for p in parts:
                p.set_color(*col)
        # вода течёт навстречу движению
        self.water.set_tex_offset(TextureStage.get_default(), 0, t * 0.75)

        pos = self.raft_pos()
        self.raft.set_pos(pos)
        self.raft.set_h(-math.degrees(w.ang))
        self.raft.set_p(2.5 * math.sin(t * 2.3))
        self.raft.set_r(2.5 * math.sin(t * 1.7 + 1))
        players = self.players()
        for i, (a, lbl) in enumerate(self.animals):
            sx, sy = w.seat_dir(i)
            seat = w.seats[i]
            bob = 0.04 * abs(math.sin(t * 30)) if seat.farting else 0.0
            a.set_pos(pos + Vec3(sx * SEAT_R, -sy * SEAT_R, 0.12 + bob))
            a.set_h(math.degrees(math.atan2(sx, sy)))
            lbl.set_pos(pos + Vec3(sx * SEAT_R * 1.1, -sy * SEAT_R * 1.1, 1.0))
            lbl.node().set_text_color(1, 1, 1, 1 if i in players else 0.35)
            if seat.farting and w.state == "play":
                self.emit_gas(pos, sx, sy)
                snd = self.sfx[i] if self.sfx else None
                if snd and snd.status() != snd.PLAYING:
                    snd.set_play_rate(random.uniform(0.85, 1.2))
                    snd.play()
        for ev in w.events:
            if ev == "hit":
                self.shake = 0.35
                if self.bonk:
                    self.bonk.play()
        w.events.clear()

        if w.state == "play" and w.falling <= 0 and w.countdown <= 0:
            self.ring_timer -= dt
            if self.ring_timer <= 0 and self.ring_pool:
                self.ring_timer = 0.22
                r = self.ring_pool.pop()
                r.show()
                r.set_pos(to3d(w.x, w.y, 0.03))
                self.rings.append([r, 0.0])
        alive = []
        for r in self.rings:
            r[1] += dt
            k = r[1] / 1.6
            if k >= 1:
                r[0].hide()
                self.ring_pool.append(r[0])
                continue
            r[0].set_scale(0.7 + 0.6 * k, 0.7 + 0.6 * k, 1)
            r[0].set_color(1, 1, 1, 0.65 * (1 - k))
            alive.append(r)
        self.rings = alive

        keep = []
        for p in self.puffs:
            p.life -= dt
            if p.life <= 0:
                p.np.hide()
                self.puff_pool.append(p.np)
                continue
            p.pos += p.vel * dt
            p.vel *= (1 - 2.2 * dt)
            p.vel.z += 0.4 * dt
            k = p.life / p.max
            p.size = min(0.45, p.size + dt * 0.35)
            p.np.set_pos(p.pos)
            p.np.set_scale(p.size)
            p.np.set_color(gfx.C_GAS[0] + (1 - k) * 0.2, gfx.C_GAS[1], gfx.C_GAS[2] + (1 - k) * 0.3, 0.9 * k ** 0.7)
            keep.append(p)
        self.puffs = keep

        self.update_camera(dt, pos)

    def emit_gas(self, pos, sx, sy):
        out = Vec3(sx, -sy, 0)
        w = self.world
        base = pos + out * (SEAT_R + 0.2) + Vec3(0, 0, 0.2)
        for _ in range(2):
            if not self.puff_pool:
                return
            p = Puff()
            p.np = self.puff_pool.pop()
            p.np.show()
            spread = Vec3(random.uniform(-0.6, 0.6), random.uniform(-0.6, 0.6), random.uniform(-0.1, 0.4))
            p.pos = Vec3(base)
            p.vel = out * random.uniform(2.0, 3.8) + spread + Vec3(w.vx / U * 0.5, -w.vy / U * 0.5, 0)
            p.life = p.max = random.uniform(0.6, 1.1)
            p.size = random.uniform(0.09, 0.16)
            self.puffs.append(p)

    def update_camera(self, dt, pos):
        w = self.world
        fx, fy = sim.flow_dir(max(-500, -w.y) + 250)
        fwd = Vec3(fx, -fy, 0)
        fwd.normalize()
        focus = Vec3(pos) if w.falling <= 0 else to3d(w.x, w.y)
        want = focus - fwd * 3.9 + Vec3(0, 0, 2.7)
        look = focus + fwd * 2.0 + Vec3(0, 0, 0.4)
        if w.state == "menu":
            a = w.t * 0.15
            want = focus + Vec3(math.sin(a) * 5, -math.cos(a) * 5, 2.8)
            look = focus
        if self.cam_pos is None:
            self.cam_pos, self.cam_look = want, look
        self.cam_pos = self.cam_pos + (want - self.cam_pos) * min(1, dt * 4)
        self.cam_look = self.cam_look + (look - self.cam_look) * min(1, dt * 6)
        jitter = Vec3(random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1)) * self.shake * 0.25
        self.shake = max(0, self.shake - dt)
        self.camera.set_pos(self.cam_pos + jitter)
        self.camera.look_at(self.cam_look)
        self.camLens.set_fov(62)


def main():
    FartApp().run()


if __name__ == "__main__":
    main()
    sys.exit(0)
