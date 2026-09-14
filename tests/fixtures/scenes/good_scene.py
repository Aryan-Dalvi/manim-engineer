from manim_engineer.kit import *


class GoodScene(Scene):
    def construct(self):
        self.next_section("b1_intro")
        title = section_title("Softmax temperature")
        eq = MathTex(r"p_i = \frac{e^{z_i/T}}{\sum_j e^{z_j/T}}", font_size=EQ_SIZE)
        place(eq, "main_upper")
        self.play(Write(title), run_time=RT_WRITE)
        self.play(Write(eq), run_time=RT_WRITE)
        self.wait(HOLD_MEDIUM)
        self.next_section("b2_plot")
        axes, graph, labels = plot_in_region(
            lambda x: x**2 / 9,
            [-3, 3, 1],
            [0, 1, 0.5],
            region="main_lower",
            x_label="z",
            y_label="p",
        )
        self.play(Create(axes), run_time=1)
        self.play(Create(graph), run_time=1.5)
        note = caption("Lower T sharpens the distribution")
        self.play(FadeIn(note, shift=UP * 0.2), run_time=RT_FADE)
        self.wait(HOLD_LONG)
        self.next_section("b3_outro")
        fade_all(self)
