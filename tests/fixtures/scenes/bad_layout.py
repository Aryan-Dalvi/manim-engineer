from manim_engineer.kit import *


class BadLayoutScene(Scene):
    def construct(self):
        self.next_section("b1_intro")
        wide = Text(
            "This is a very long line of text that should run off the frame edge", font_size=48
        )
        wide.shift(RIGHT * 4)
        self.play(Write(wide), run_time=1)
        self.next_section("b2_overlap")
        a = Text("Overlapping A", font_size=36).move_to(ORIGIN)
        b = Text("Overlapping B", font_size=36).move_to(ORIGIN + DOWN * 0.1)
        self.play(FadeIn(a), FadeIn(b), run_time=1)
        tiny = Text("tiny caption", font_size=8).move_to(DOWN * 2)
        c = Circle().move_to(RIGHT * 7 + UP * 3)
        self.play(FadeIn(tiny), Create(c), run_time=1)
        self.wait(1)
