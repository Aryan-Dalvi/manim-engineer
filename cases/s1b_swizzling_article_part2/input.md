# Swizzling explained properly, part 2: base, the 32B/64B/128B modes, and the benchmark

## What about `base`?

*Base is the number of least-sig bits to keep constant.* Why do we need this?

Clues come from the matrix load instructions. `ldmatrix` receives the starting address of a matrix
row, where each row contains either 8 elements of 16 bits each (the `.m8n8.b16` shape) or 16
elements of 8 bits each (the `.m16n16.b8` shape) — exactly 16 bytes either way. Documentation states
that *consecutive instances of row need not be stored contiguously in memory*, and that when
reading 8×8 matrices a group of four consecutive threads loads 16 bytes, so matrix addresses must
be naturally aligned accordingly. So each 16-byte row must be contiguous, but we can place rows
wherever we want as long as the within-row layout doesn't change.

Picture two strips of eight cells side by side: a purple strip, row 0, running `0x00000000` to
`0x0000000F`, and a blue strip, row 1, running `0x00000010` to `0x0000001F`. *Original*: each strip
reads as four solid cells then four hatched cells. *Illegal*: within each strip the fills now
alternate solid-hatched-solid-hatched — elements shuffled *inside* a 16-byte row. *OK*: the blue
strip sits where the purple one was and vice versa — whole rows traded, interiors untouched.
Swapping entire rows is legal; permuting elements within rows is not.

In other words, the 4 least significant bits of every element's address must be kept constant.
`base = 4` does exactly this: the XOR mask never reaches below bit 4, so addresses move only in
16-byte steps.

Another way of thinking about `base` is that it sets the atomicity of the swizzle.
`Swizzle(2, 0, 3)` works on a grid of $2^2 = 4$ rows and $2^3 = 8$ columns where each element is
$2^0 = 1$ byte. `Swizzle(2, 4, 3)` is the same except each element is now $2^4 = 16$ bytes.

So `Swizzle(bits, base, shift)` is: `bits` = number of bits for the row index; `shift` = number of
bits for the column index; `base` = $\log_2$ of the swizzle atomicity. On the address, for positive
`shift`, the whole thing is one expression:

$$\mathrm{addr}' = \mathrm{addr} \oplus \Big(\big((\mathrm{addr} \gg (\texttt{base}+\texttt{shift})) \,\&\, (2^{\texttt{bits}}-1)\big) \ll \texttt{base}\Big)$$

## 32B, 64B and 128B swizzles

One piece of arithmetic first. From here our grid is 8 rows by 8 columns of 16-byte cells, so one
grid row is $8 \times 16 = 128$ bytes — one full lap of the 32 banks. Cell $(r,c)$ begins at byte
$128r + 16c$, so

$$\mathrm{bank}(r,c) = \left\lfloor \frac{128r + 16c}{4} \right\rfloor \bmod 32 = (32r + 4c) \bmod 32 = 4c$$

The row index vanishes. **A 16-byte cell always occupies banks $4c$ through $4c+3$, decided purely
by its column.** Column 0 is banks 0–3, column 1 is banks 4–7, column 7 is banks 28–31. That is why
"spread the columns out" and "spread the banks out" are the same instruction.

### Swizzle 32B

Swizzle 32B is `Swizzle(1, 4, 3)`. Picture two 8×8 grids stacked vertically. The top one is
unswizzled, holding 0 through 63 in raster order, with a span label across the top reading
`128B = 8 x 16B`; its eight columns are colour-coded (column 0 red, 1 orange, 2 yellow, 3 green,
4 cyan, 5 blue, 6 violet, 7 magenta) so we can tell where each sub-matrix ends up. The bottom grid
is captioned `Swizzle 32B`, with a vertical span label on its left reading `32B = 2 x 16B` covering
its first two rows, and reads:

```
row 0:  0  1  2  3  4  5  6  7
row 1:  9  8 11 10 13 12 15 14
row 2: 16 17 18 19 20 21 22 23
row 3: 25 24 27 26 29 28 31 30
row 4: 32 33 34 35 36 37 38 39
row 5: 41 40 43 42 45 44 47 46
row 6: 48 49 50 51 52 53 54 55
row 7: 57 56 59 58 61 60 63 62
```

`bits=1` means we replace the LSB of the column index by XORing it with the LSB of the row index.
For even rows (0, 2, 4, 6) the row index ends in a 0 bit, so the column index doesn't change
($x \oplus 0 = x$). For odd rows (1, 3, 5, 7) the row index ends in a 1 bit, so the last bit of
every column index is flipped: every column $2n$ swaps with column $2n+1$. Row 1, which used to
read $[8, 9, 10, 11, 12, 13, 14, 15]$, now reads $[9, 8, 11, 10, 13, 12, 15, 14]$. In the odd rows
the colours swap pairwise too — orange, red, green, yellow, blue, cyan, magenta, violet.

Check that against the address formula. Cell (row 1, column 0) starts at byte $128$ = `0b010000000`;
$128 \oplus (((128 \gg 7)\,\&\,1) \ll 4) = 128 \oplus 16 = 144 = 128 \cdot 1 + 16 \cdot 1$, i.e.
column 1. Symmetrically, cell (row 1, column 1) at byte 144 becomes byte 128, column 0. The pair
has swapped.

Each cell here is a 16-byte row consumed by `ldmatrix`, and each column of the non-swizzled layout
is an 8×8 sub-matrix of two-byte elements. Following the colors, Swizzle 32B repeats itself after
two 16B rows. Is that why it's called Swizzle 32B? Or is it because any two 16B cells of the same
color can be read/written without bank conflicts? Who knows. (For the record, CuTe's layout atoms
answer it: its `SW32` atom is 8 rows by 256 bits = 32 bytes wide, `SW64` is 8 by 512 bits = 64
bytes, `SW128` is 8 by 1024 bits = 128 bytes. The name is the contiguous width of the swizzle atom
— 2, 4 or 8 sixteen-byte cells.)

A single call to `ldmatrix.m8n8.b16` consumes all elements of one color in the original grid.
Without swizzling we'd load eight 16B rows from the same column — elements 0, 8, 16, 24, 32, 40,
48, 56, all sitting in banks 0–3 — an 8-way bank conflict and an 8-cycle wait. Swizzle 32B improves
this to a 4-cycle wait by spreading every color across two columns: that colour now occupies columns
0, 1, 0, 1, 0, 1, 0, 1, i.e. banks 0–3 and 4–7, four cells apiece. But we can do better.

### Swizzle 64B

Similar XOR math yields `Swizzle(2, 4, 3)` — replace the 2 LSBs of the column index by XORing them
with the 2 LSBs of the row index. Same `128B = 8 x 16B` span on top, caption `Swizzle 64B`, and a
left-hand span reading `64B = 4 x 16B` covering four rows:

```
row 0:  0  1  2  3  4  5  6  7
row 1:  9  8 11 10 13 12 15 14
row 2: 18 19 16 17 22 23 20 21
row 3: 27 26 25 24 31 30 29 28
row 4: 32 33 34 35 36 37 38 39
row 5: 41 40 43 42 45 44 47 46
row 6: 50 51 48 49 54 55 52 53
row 7: 59 58 57 56 63 62 61 60
```

Row 2 is the clearest new case: $r = 2$, and $c \oplus 2$ sends columns $0,1,2,3,4,5,6,7$ to
$2,3,0,1,6,7,4,5$, so position $c$ holds element $16 + (c \oplus 2)$ — `18 19 16 17 22 23 20 21`.
Swizzle 64B repeats every 4 rows of 16 B because $r \,\&\, 3$ cycles with period 4.

Following the colors, one `ldmatrix.m8n8.b16` call loads from four distinct columns — the original
column 0 now sits at columns 0, 1, 2, 3, 0, 1, 2, 3 — which is $4 \times 4 = 16$ SMEM banks,
reducing our bank-conflict degree to 2. But as you guessed, we can do yet better.

### Swizzle 128B

`Swizzle(3, 4, 3)`, repeating after every 8 rows of 16 B. Its diagram spans `128B = 8 x 16B` both
across the top and down the left side:

```
row 0:  0  1  2  3  4  5  6  7
row 1:  9  8 11 10 13 12 15 14
row 2: 18 19 16 17 22 23 20 21
row 3: 27 26 25 24 31 30 29 28
row 4: 36 37 38 39 32 33 34 35
row 5: 45 44 47 46 41 40 43 42
row 6: 54 55 52 53 50 51 48 49
row 7: 63 62 61 60 59 58 57 56
```

Row 5 is a good spot check: position 7 holds element $40 + (7 \oplus 5) = 42$, so element 42 —
originally cell (5, 2) — has travelled to column $2 \oplus 5 = 7$. In addresses,
$128 \cdot 5 + 16 \cdot 2 = 672$, and $672 \oplus (((672 \gg 7)\,\&\,7) \ll 4) = 672 \oplus 80 = 752
= 128 \cdot 5 + 16 \cdot 7$.

One `ldmatrix.m8n8.b16` now reads eight distinct columns — 0 through 7 — hitting all 32 SMEM banks
and eliminating all bank conflicts. Perfect. The general rule on this 8×8 grid of 16-byte cells:

$$\text{conflict degree} = \frac{8}{2^{\texttt{bits}}} = \frac{32\ \text{banks}}{4 \cdot 2^{\texttt{bits}}}$$

8-way with no swizzle, 4-way at 32B, 2-way at 64B, conflict-free at 128B.

## Sample swizzled matmul

As the CUTLASS programming guidelines wisely say: *"Performance requires it" implies measurement.*

So let's measure. I benchmarked matrix multiplication kernels with basic optimizations —
vectorized GMEM accesses, block-tiling, tensor cores — so they aren't stupidly slow. All kernels are
totally identical apart from their swizzle mode.

We compute $C = AB$ with $m=n=k=8192$, on an A100 80GB PCIe whose dense FP16 tensor-core peak is
312 TFLOP/s. The kernel uses a 128×128 CTA tile with `BLOCK_K = 64`, a 32×64 warp tile,
`mma.sync.aligned.m16n8k8.row.col.f32.f16.f16.f32`, `ldmatrix.x2` for A fragments, `ldmatrix.x1`
for B fragments, and 256 threads (8 warps) per block. It was originally targeted at Turing (sm75),
but microarchitectural bugs prevented accurate profiling; it was compiled for and run on sm80, and
does not use post-Turing features like `cp.async` or `stmatrix`. Its SMEM footprint is
$\max(2 \cdot 128 \cdot 64 \cdot 2,\ 128 \cdot 128 \cdot 4) = 65536$ bytes = 64 KB.

### Results — input swizzle

Swizzling only the input tiles for $A$ and $B$ gives a bar chart titled *Matmul TFLOP/s vs. input
swizzle mode*, four bars against a `TFLOP/s` axis running 0 to 100: **none = 36.19**,
**32B = 74.97**, **64B = 95.55**, **128B = 98.48**.

As expected, wider swizzling modes give us more FLOP/s — 2.07×, 2.64× and 2.72× over the baseline.

More interestingly, the gains diminish: 32B → 64B is worth +20.58 TFLOP/s, while 64B → 128B buys
only +2.93. If bank-conflict degree halves with every doubling of the swizzle width, then max
possible SMEM bandwidth doubles. But our FLOP/s don't show this exponential gain, because as we
eliminate bank conflicts, other operations begin to dominate. Nsight Compute supports this.

The stall chart is titled *% of stall cycles by stall reason*, with `Input swizzle mode` on the
x-axis and `% of all stall cycles` on the y-axis running to 60, and four grouped series.
`mio_throttle` falls **58.2 → 32.9 → 5.9 → 1.8 %** across none / 32B / 64B / 128B;
`short_scoreboard` goes **4.9 → 12.7 → 2.9 → 1.3 %**; `long_scoreboard` climbs
**18.8 → 15.7 → 23.8 → 25.6 %**; `math_pipe_throttle` climbs **0.7 → 5.1 → 18.4 → 21.5 %**. (These
four don't sum to 100 % — the remaining stall reasons aren't plotted.)

With no-swizzle and 32B, memory I/O instruction queue waiting (MIO Throttle) accounts for the vast
majority of stall cycles. At 64B and above it becomes nearly negligible, with GMEM latency (Long
Scoreboard) and math instructions (Math Pipe Throttle) dominating instead. When we eliminate SMEM
bank conflicts, we spend a larger percentage of our time doing math and accessing GMEM.

### Results — output swizzle

What happens if we swizzle the output $C$ instead? The companion chart, *Matmul TFLOP/s vs. output
swizzle mode*, has a y-axis that only needs to run to 35, and reads **none = 36.19**,
**32B = 36.21**, **64B = 36.2**, **128B = 36.23**. Total spread: 0.04 TFLOP/s, about a tenth of a
percent.

Wow, that's kinda sad. What happened here (or not)?

Eliminating bank conflicts for our $C$ tile does practically nothing, while eliminating them for
$A$ and $B$ almost triples our FLOP/s. Two reasons.

**1. SMEM loads of $A$ and $B$ account for far more SMEM traffic than stores of $C$.** Nsight
Compute tells us exactly how much: `sm__sass_data_bytes_mem_shared_op_st.sum` is 17.45 GB,
`sm__sass_data_bytes_mem_shared_op_ldsm.sum` is 51.54 GB, and
`sm__sass_data_bytes_mem_shared_op_ld.sum` is 0.27 GB. (Matrix loads, `LDSM`, are distinguished
from regular loads, `LD`.) Loads total 51.81 GB; stores total 17.45 GB. That's a 3× difference.

Why almost exactly 3×? Our SMEM accesses are: store $A$ and $B$ from GMEM → SMEM; load $A$ and $B$
from SMEM → RMEM for the matmul; store the $C_{FP32}$ tile from RMEM → SMEM; load $C_{FP32}$ from
SMEM → RMEM to downcast to FP16 before writing to GMEM. Naively it seems each of $A$, $B$, $C$ is
stored and loaded once, so the counts should match. Not true.

Picture the reuse diagram: an `A SMEM tile: 128x64` box on the left, a `B SMEM tile: 64x128` box
along the top, and the `C SMEM tile: 128x128` in the middle, carved into a 4-row by 2-column
arrangement of `Warp tile: 32x64` blocks. Highlight the top row of two warp tiles: both pull the
same red A fragment — *A MMA tile is loaded 2x*. Highlight the left column of four warp tiles: all
four pull the same red B fragment — *B MMA tile is loaded 4x*. With 2 warp tiles per SMEM tile row
and 4 per SMEM tile column, and $|A| = |B|$ per k-step:

$$\frac{\text{SMEM loads}}{\text{SMEM stores}} = \frac{2|A| + 4|B|}{|A| + |B|} = \frac{2+4}{2} = 3$$

In bytes per k-step per thread block, stores are $(128 \cdot 64 + 64 \cdot 128) \times 2 = 32768$ B
and loads are $2(128 \cdot 64) \times 2 + 4(64 \cdot 128) \times 2 = 98304$ B. Exactly 3×.

But 3× doesn't explain the *total* absence of any effect from output swizzling. The key is where
the stores come from. Almost all are stores of $A$ and $B$ from GMEM → SMEM, not stores of $C$ from
RMEM → SMEM: we compute each output tile once, while tiles of $A$ and $B$ are reloaded across
thread blocks. Shared stores total 17.45 GB, but writes of $C_{FP32}$ account for only

$$(8192 \times 8192)\ \text{elements} \times 4\ \text{B} = 268\ \text{MB}$$

which is 1.5 % of that. They might as well be a rounding error.

Why reload the same A and B tiles from GMEM at all? There's no way to fit $A$ and $B$ into SMEM —
each is $8192 \times 8192 \times 2 = 134$ MB, while modern GPUs have a few hundred KB of SMEM at
most. Each thread block computes one output tile, SMEM is shared only within a block, and the same
tiles of $A$ and $B$ are needed for multiple output tiles of $C$. Picture the second diagram:
`A (GMEM)` as a tall strip on the left, `B (GMEM)` as a wide strip on top, `C (GMEM)` as a grid of
output tiles with the top-left, top-right and bottom-left tiles highlighted, annotated *A and B
SMEM tiles reloaded across blocks*, *# of B SMEM loads = no. of rows = M ÷ height of C SMEM tile*,
and *No. of A SMEM loads = no. of columns = N ÷ width of C SMEM tile*. The same A strip feeds every
tile across a row; the same B strip feeds every tile down a column. For a 128×128 tile:

$$\frac{8192}{128} = 64$$

$A$ is copied 64 times from GMEM to SMEM, and so is $B$. Total bytes stored from GMEM → SMEM:

$$64 \times (8192 \times 8192) \times 2\ \text{B} \times 2 = 17.18\ \text{GB}$$

which closely matches our counter of 17.45 GB, the remaining 0.27 GB being the $C$ stores.

The effect of duplicate SMEM → RMEM loads stacks multiplicatively on top of the duplicate
GMEM → SMEM stores. Hence SMEM bytes loaded is 3× SMEM bytes stored, which is 64× the size of A and
B in GMEM.

**2. Our $C$ store conflicts are of lower degree than our $A$ and $B$ loads.** Nsight Compute says
*the memory access pattern for shared stores might not be optimal and causes on average a 4.5-way
bank conflict across all 34 603 008 shared store requests.* So with non-swizzled input and output,
our SMEM loads are 8-way conflicted while our stores are only 4(ish)-way conflicted.

This surprised me. The PTX reference documents the $C$ fragment layout for `mma.sync.m16n8k8` as a
16-row by 8-column table: row 0 holds `T0:{c0,c1}` in columns 0–1, `T1:{c0,c1}` in columns 2–3,
`T2:{c0,c1}` in 4–5, `T3:{c0,c1}` in 6–7; row 1 holds T4 through T7; down to row 7 with T28 through
T31. Rows 8 through 15 repeat the identical pattern with each lane's `{c2,c3}`. Equivalently:
`groupID = laneid >> 2`, `threadID_in_group = laneid % 4`, `row = groupID` for `c0`/`c1` and
`groupID + 8` for `c2`/`c3`, and `col = threadID_in_group * 2 + (i & 1)`.

Our RMEM → SMEM store is a single `st.shared.v2.u32` per fragment pair, so each thread writes two
4-byte floats in one instruction. Each row of the $C_{FP32}$ tile is 128 × 4 = 512 bytes apart.
Since that is a multiple of 128, all elements in the same column map to the same bank:

$$\mathrm{bank} = (\text{row} \times 128 + \text{col}) \bmod 32 = \text{col} \bmod 32$$

And since every 4th thread writes the same columns — lanes 0, 4, 8, 12, 16, 20, 24, 28 all have
`threadID_in_group = 0` — our conflict degree should be 32 ÷ 4 = 8, just like our loads. Right?

Wrong. This fails to account for a crucial hardware nuance: SMEM accesses are split into 128-byte
transactions. Each warp writes 8 bytes per thread × 32 threads = 256 bytes:

$$32\ \text{threads} \times 8\ \text{B} = 256\ \text{B} = 2 \times 128\ \text{B}$$

These are split into two transactions, so only half the warp's writes execute concurrently. With 16
lanes contending at a time, only 4 share any given column pair — halving the average bank-conflict
degree from 8 to 4.

## Conclusion / appendix / post-article word vomit

Writing this sent me down an insane rabbit hole, and I hope you enjoyed diving into it with me.
Only about half of the noteworthy things I encountered made it in. Honorable mentions:

### `__launch_bounds__` for avoiding unintentional register reuse

I first compared all swizzled kernels to a padded kernel, which solves bank conflicts by padding
input and output rows in SMEM. The padded kernel was unexpectedly slower than the swizzled one,
despite doing less math and also avoiding all bank conflicts. Wading through SASS revealed that
`ptxas` reused registers during the GMEM → SMEM load for the padded kernel but not the swizzled
kernel. This was ostensibly a heuristic trying to reduce register pressure, but what it actually
did was introduce a crap ton of extra read-after-write dependencies that totally prevented ILP
between GMEM loads. Additionally: the padded kernel was way under the register budget anyway; the
kernel's occupancy was limited by SMEM usage, not register pressure, so fewer registers per thread
would not have given me extra CTAs per SM; and Long Scoreboard stalls (GMEM latency) remain the
dominant bottleneck at 25.6 % of stall cycles in the 128B configuration. Slowing down GMEM loading
further would be terrible. Indeed, the bug gave me a 25 % slowdown on a Titan RTX.

`ptxas`, what are you doing?! Explicitly telling the compiler that I only intended to launch one
CTA per SM — `__launch_bounds__(n_threads, 1)` with `n_threads = 256` — fixed it, letting the
kernel use as many damn registers as it wanted. Both a skill issue on my part and a badly tuned
compiler heuristic.

### sm75 uarch bug(?)

On all Turing cards I tested, 128B swizzle was unexpectedly slower than 64B. Somehow, Long
Scoreboard stall cycles increased more than MIO and Short Scoreboard stalls fell! This can't be
explained by "GMEM latency is no longer hidden by SMEM latency" because it doesn't account for why
*total* stall cycles increased — that explanation only works if stall cycles stayed the same.

The bug disappeared on sm80 and later. (I tested a Tesla T4, Titan RTX, RTX 3090, RTX 4090, RTX
4060 mobile, RTX 3060 LHR, A100 80GB PCIe, and H100 96GB PCIe.) I suspect a Turing-specific
microarchitectural bug: SMEM and GMEM accesses share a lot of hardware machinery, so maybe those
units become more contended on Turing than on later generations once bank conflicts disappear? I
don't know. If any Nvidia engineers wanna explain an eight-year-old uarch that has long reached
EOL, feel free.

