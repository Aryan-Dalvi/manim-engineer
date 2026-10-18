import os
from manim import *


class BadStaticScene(Scene):
    def construct(self):
        eq = MathTex(r"\frac{1}{2} \undefinedmacro")
        s = Square()
        self.play(ShowCreation(eq))
        self.play(s.animate.shift_right(3))
        blob = ColorfulBlob()
        self.play(FadeIn(blob), run_time=2)
        self.wait(3)
