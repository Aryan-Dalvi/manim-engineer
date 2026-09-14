from manim_engineer.kit import *


class RuntimeErrorScene(Scene):
    def construct(self):
        self.next_section("b1_intro")
        s = Square()
        self.play(Create(s), run_time=1)
        self.play(s.animate.shift_right(3))
        self.wait(1)
