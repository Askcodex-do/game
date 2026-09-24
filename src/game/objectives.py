"""Mission objectives and stage flow.

Stage One is a five-step infiltration:

  1. Disable all seven security cameras  (primary)
  2. Destroy the two fuelled bowsers     (primary)
  3. Recover three pieces of intel       (primary)
  4. Eliminate the colonel                (primary)
  5. Reach the extraction pad            (primary)

Optional secondary goals reward careful play: never trip the alarm, and finish
without killing more guards than necessary. Objectives are data objects so the
HUD and the completion checks read from one source of truth.
"""

from ..config import INTEL_COUNT


class Objective:
    """One mission goal with a progress counter."""

    def __init__(self, key, text, target=1, primary=True, hint=""):
        self.key = key
        self.text = text
        self.target = target
        self.progress = 0
        self.primary = primary
        self.hint = hint
        self.done = False
        self.just_completed = False

    def set_progress(self, value):
        value = max(0, min(self.target, value))
        if value == self.progress and self.done:
            return False
        self.progress = value
        was_done = self.done
        self.done = self.progress >= self.target
        if self.done and not was_done:
            self.just_completed = True
            return True
        return False

    def advance(self, amount=1):
        return self.set_progress(self.progress + amount)

    @property
    def status_text(self):
        if self.target <= 1:
            return self.text
        return f"{self.text} ({self.progress}/{self.target})"

    def consume_completion(self):
        flag = self.just_completed
        self.just_completed = False
        return flag


class MissionState:
    """Tracks objectives, alarm history and the overall stage outcome."""

    def __init__(self, intel_count=INTEL_COUNT, cameras=7, trucks=2):
        self.objectives = {
            "cameras": Objective("cameras", "Disable all security cameras",
                                 target=cameras,
                                 hint="Shoot the lens housing or creep past"),
            "trucks": Objective("trucks", "Destroy both fuel bowsers",
                                target=trucks,
                                hint="The fuelled trucks in the motor pool"),
            "intel": Objective("intel", "Recover classified intel",
                               target=intel_count,
                               hint="Three laptops are hidden in the depot"),
            "colonel": Objective("colonel", "Eliminate the colonel",
                                 hint="He patrols the barracks at night"),
            "extraction": Objective("extraction", "Reach the extraction pad",
                                    hint="North-east landing pad"),
            # Secondary, tracked but not required to win.
            "ghost": Objective("ghost", "Complete without tripping the alarm",
                               primary=False),
            "marksman": Objective("marksman", "Fewer than 6 guards eliminated",
                                  primary=False),
        }
        self.order = ["cameras", "trucks", "intel", "colonel", "extraction"]
        self.alarm_count = 0
        self.kills = 0
        self.camera_kills = 0
        self.truck_kills = 0
        self.intel_collected = 0
        self.colonel_dead = False
        self.extracted = False
        self.elapsed = 0.0
        self.failed = False
        self.fail_reason = ""
        self.completed = False
        self.started = False

    # ------------------------------------------------------------- progress --
    def begin(self):
        self.started = True

    def objective(self, key):
        return self.objectives[key]

    def on_alarm(self):
        self.alarm_count += 1
        # Tripping the alarm once forfeits the ghost bonus, permanently.
        ghost = self.objectives["ghost"]
        if not ghost.done and ghost.progress == 0:
            ghost.set_progress(0)
        return self.objectives["cameras"]

    def on_camera_destroyed(self):
        self.camera_kills += 1
        obj = self.objectives["cameras"]
        changed = obj.set_progress(len([]) + self.camera_kills)
        return changed

    def sync_cameras(self, destroyed_count):
        return self.objectives["cameras"].set_progress(destroyed_count)

    def on_truck_destroyed(self):
        self.truck_kills += 1
        return self.objectives["trucks"].set_progress(self.truck_kills)

    def on_intel(self):
        self.intel_collected += 1
        return self.objectives["intel"].set_progress(self.intel_collected)

    def on_colonel_killed(self):
        self.colonel_dead = True
        return self.objectives["colonel"].set_progress(1)

    def on_guard_killed(self, kind="soldier"):
        self.kills += 1
        marksman = self.objectives["marksman"]
        # This one is inverted: "done" means the player stayed under budget.
        marksman.progress = self.kills
        marksman.done = self.kills < 6
        return False

    def on_extracted(self):
        self.extracted = True
        return self.objectives["extraction"].set_progress(1)

    def fail(self, reason):
        self.failed = True
        self.fail_reason = reason

    def update(self, dt):
        if self.started and not self.completed and not self.failed:
            self.elapsed += dt
        # The ghost objective completes only on extraction while alarm-free.
        if self.extracted and not self.objectives["ghost"].done:
            if self.alarm_count == 0:
                self.objectives["ghost"].set_progress(1)

    # ----------------------------------------------------------- completion --
    @property
    def primaries_done(self):
        return all(self.objectives[key].done for key in self.order)

    @property
    def mission_complete(self):
        return self.extracted and all(self.objectives[k].done
                                      for k in ("cameras", "trucks", "intel",
                                                "colonel"))

    def consume_completions(self):
        """Return the objectives completed since the last call (for toasts)."""
        completed = []
        for obj in self.objectives.values():
            if obj.consume_completion():
                completed.append(obj)
        return completed

    def hud_list(self):
        out = []
        for key in self.order:
            obj = self.objectives[key]
            out.append({
                "text": obj.status_text,
                "done": obj.done,
                "primary": obj.primary,
            })
        for key in ("ghost", "marksman"):
            obj = self.objectives[key]
            if key == "marksman":
                text = f"{obj.text} ({self.kills})"
                out.append({"text": text, "done": obj.done, "primary": False})
            else:
                out.append({"text": obj.text, "done": obj.done, "primary": False})
        return out

    def rank(self):
        """Score the run for the debrief screen."""
        score = 0
        score += 40 if self.objectives["ghost"].done else 0
        score += max(0, 25 - self.kills * 4)
        score += 20 if self.elapsed < 420 else (10 if self.elapsed < 720 else 0)
        score += 15 if not self.failed else 0
        if score >= 85:
            return "S", score
        if score >= 70:
            return "A", score
        if score >= 55:
            return "B", score
        if score >= 40:
            return "C", score
        return "D", score


BRIEFING = [
    "SITUATION",
    "  A supply depot in the northern sector is staging fuel and munitions",
    "  for an enemy push. Intelligence places a command element on site.",
    "",
    "MISSION  (Stage One: Silent Depot)",
    "  1. Disable all seven security cameras before they raise the alarm.",
    "  2. Destroy the two fuelled bowsers in the motor pool.",
    "  3. Recover three classified intel packages.",
    "  4. Eliminate the colonel commanding the depot.",
    "  5. Exfiltrate via the north-east landing pad.",
    "",
    "SUPPORT",
    "  Knife and suppressed pistol are already on you. Better weapons and",
    "  medical supplies are cached around the depot - search the yards.",
    "",
    "NOTE",
    "  You are one operator against a garrison. Stay low, use the dark,",
    "  and remember: a dead depot is louder than a quiet one.",
]
