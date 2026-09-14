# Swizzling at the Frontier: Where the XOR Goes Next

## Swizzling is a shear matrix over GF(2)

Write a shared-memory byte offset as a vector of bits over the two-element field, $a \in \mathbb{F}_2^{d}$, and every swizzle in every GPU library becomes one matrix multiplication $a \mapsto Ma$. Take the 128-byte swizzle on a 1024-byte region, so $d = 10$. Bits $a_7a_8a_9$ are the row index among eight rows of 128 bytes, bits $a_4a_5a_6$ index the 16-byte chunk inside a row, and bits $a_0$ through $a_3$ are never touched. The map is $a'_4 = a_4 \oplus a_7$, $a'_5 = a_5 \oplus a_8$, $a'_6 = a_6 \oplus a_9$, that is $M = I + E$ with ones at positions $(4,7)$, $(5,8)$ and $(6,9)$. Byte offset $672 = \texttt{0x2A0}$ lies in row $672 \gg 7 = 5$, chunk $(672 \gg 4) \wedge 7 = 2$, and lands at chunk $2 \oplus 5 = 7$, offset $752 = \texttt{0x2F0}$. Sorting the bits so chunk bits come first gives the general form

$$M = \begin{bmatrix} I_n & C \\ 0 & I_m \end{bmatrix},$$

block unitriangular, hence invertible for every $C$. Here $E^2 = 0$, so $M^{-1} = M$: the swizzle is its own inverse, which is why no library ships an unswizzle function. The article's $f(r,c) = (r, c \oplus r)$ is the case $C = I$.

## CuTe packs that matrix into three integers

CUTLASS never stores a matrix. `Swizzle<BBits, MBase, SShift>` builds a mask `yyy_msk` of `BBits` bits starting at `MBase + SShift` and a mask `zzz_msk` of `BBits` bits starting at `MBase`, then evaluates one line:

```
return offset ^ shiftr(offset & yyy_msk{}, msk_sft{});
```

For `Swizzle<3,4,3>` that is `yyy_msk = 7 << 7 = 0x380` and `zzz_msk = 7 << 4 = 0x70`. Feeding it 672: masking gives `0x280`, shifting right by three gives `0x50`, and $672 \oplus 80 = 752$, the same answer as the matrix. The static assertion `abs(SShift) >= BBits` guarantees the two masks are disjoint, which is the bit-level restatement of the article's proof that $c \oplus r < N$. The three Hopper modes are `Swizzle<1,4,3>`, `Swizzle<2,4,3>` and `Swizzle<3,4,3>`, and CuTe's descriptor builder hard-asserts `MBase == 4` and `SShift == 3`. On Hopper, only a 16-byte atom over an eight-chunk span is legal, so `BBits` is the only free parameter.

## Composing a swizzle with a layout

A CuTe layout maps logical coordinates to offsets; a swizzle maps offsets to offsets. They cannot be fused into one shape-and-stride pair, so CuTe keeps them side by side in a `ComposedLayout<LayoutA, Offset, LayoutB>` evaluated as

$$R(c) = \big(\text{inner} \circ \text{offset} \circ \text{outer}\big)(c) = \text{inner}\big(\text{offset} + \text{outer}(c)\big).$$

The outer layout turns a coordinate such as $(5, 34)$ into a raw offset, the offset term adds the base address, and the inner swizzle shears the result. A composed layout deliberately exposes `shape()` and `size()` but refuses to answer `stride()`, because after the XOR there is no single stride. The canonical Hopper K-major atom is

$$\texttt{Swizzle<3,4,3>} \circ \texttt{smem\_ptr} \circ \big(\texttt{Shape<\_8,\_1024>}, \texttt{Stride<\_1024,\_1>}\big)$$

in units of bits. A bf16 tile of shape $(128, 64)$ is built by calling `tile_to_shape` on that atom, which stamps the 1024-byte pattern sixteen times down the M direction without ever changing the swizzle parameters.

## The 128B K-major atom is eight rows of 64 bf16

Upcasting the bit-level atom by $\texttt{sizeof\_bits}(\text{bf16}) = 16$ divides both extents by sixteen, giving shape $(8, 64)$ with stride $(64, 1)$ in elements: eight rows of 64 bf16, each row $64 \times 2 = 128$ bytes, the whole atom $8 \times 128 = 1024$ bytes. The 128 is $32 \text{ banks} \times 4 \text{ bytes}$, one complete sweep of shared memory; the 8 is the number of 16-byte chunks in 128 bytes, so a three-bit row index can permute a three-bit chunk index onto every chunk exactly once. PTX describes the same object as an $8 \times 8$ grid of 128-bit elements, and the eight rows are the eight rows of a core matrix, the same eight that `ldmatrix.m8n8` gathers from eight independently chosen addresses. Walk logical column 0, which is what one `ldmatrix` wants, and you visit stored chunks $0,1,2,3,4,5,6,7$: all 32 banks, zero conflicts. The 64-byte atom, $8 \times 4$ in PTX terms, sends the same walk to $0,1,2,3,0,1,2,3$ and you are back to a two-way conflict.

## Why 128B is the default: one cascading selector

CUTLASS does not search. The function `ss_smem_selector` tries the 128-byte atom first, then 64, then 32, then the non-swizzled interleaved atom, returning the first whose extent divides the block extent. For a K-major bf16 operand the test is whether the block K extent is a multiple of 64 elements; with $\texttt{BLK\_K} = 64$ the answer is yes and the search stops at the first candidate. So the mode is a function of exactly one number, the inner tile extent in bytes:

$$W = \max\{\,w \in \{128, 64, 32\} : w \mid (\texttt{BLK\_K} \cdot \text{sizeof(T)})\,\}.$$

FlashAttention-3 calls this selector for its Q, K and V tiles, so a head dimension of 64 in bf16 gives exactly 128 bytes per row and exactly the 128-byte mode. A head dimension of 32 gives 64 bytes and silently drops to the 64-byte mode. That is why attention and GEMM kernels keep choosing K-tiles that are a multiple of 64 bf16, 32 tf32 or 128 fp8: each is 128 bytes.

## TMA performs the same XOR in hardware

On Hopper and Blackwell, `cp.async.bulk.tensor` does not merely copy: the TMA unit applies the swizzle while writing into shared memory, so the kernel never computes a swizzled store address. PTX prints the pattern as a table of 16-byte cells for a 1024-byte-aligned destination, and it is the XOR table entry by entry. Row 0 reads $0,1,2,3,4,5,6,7$; row 1 reads $1,0,3,2,5,4,7,6$; row 5 reads $5,4,7,6,1,0,3,2$. Position $j$ of row $r$ holds source chunk $r \oplus j$, so for a box of 64 bf16 per row, row 5's 16-byte chunk 2 lands at chunk $2 \oplus 5 = 7$. The 64-byte mode repeats after four rows and needs 512-byte alignment; the 32-byte mode repeats after two and needs 256. This is the same $M$ as before, executed by a DMA engine rather than by `ptxas`, which is why a CuTe `Swizzle<3,4,3>` layout and a `CU_TENSOR_MAP_SWIZZLE_128B` tensor map describe byte-identical shared memory.

## The box constraint that decides your tile shape

Because the TMA unit stamps a fixed-width pattern, the copy descriptor carries a hard rule. `cuTensorMapEncodeTiled` states that when interleaving is off and swizzling is on, the bounding box inner dimension, computed as `boxDim[0]` multiplied by the element size, must not exceed the swizzle size:

$$\texttt{boxDim}[0] \cdot \text{sizeof(T)} \le W, \qquad W \in \{32, 64, 128\}.$$

A box of 64 bf16 is 128 bytes and just fits `CU_TENSOR_MAP_SWIZZLE_128B`. A box of 32 bf16 is 64 bytes and is rejected for the 128-byte mode, so you fall back to `SWIZZLE_64B` and accept a two-way conflict on the column walk. A box of 128 bf16 is 256 bytes and is rejected outright, so a wide K-tile is expressed as several boxes of 64 rather than one box of 128. The surrounding rules are equally rigid: the global address must be 16-byte aligned, the global strides must be multiples of 16 and below $2^{40}$, and the tensor map itself must be 64-byte aligned.

## The WGMMA descriptor spends two bits on the swizzle

A Hopper `wgmma.mma_async` never receives a pointer. It receives a 64-bit matrix descriptor: bits 13 to 0 hold the encoded start address, bits 29 to 16 the leading dimension byte offset, bits 45 to 32 the stride dimension byte offset, bits 51 to 49 a base offset, and bits 63 to 62 the swizzle mode. Every address-like field passes through

$$\texttt{encode}(x) = (x \wedge \texttt{0x3FFFF}) \gg 4,$$

which discards the low four bits and so forces 16-byte alignment on all three. The two-bit mode field is deliberately not monotone: 0 is no swizzle, 1 is 128-byte, 2 is 64-byte, 3 is 32-byte, mirrored in CUTLASS as `LayoutType { INTERLEAVE = 0, B128 = 1, B64 = 2, B32 = 3 }`. For an MN-major bf16 operand with 64-byte swizzling, PTX works the example out: the leading byte offset is $256 \times 2 = 512$ bytes, encoded as $512 \gg 4 = 32$, and the stride byte offset is $512 \times 2 = 1024$ bytes, encoded as 64. The base offset is zero only when the tile starts on a 1024-byte boundary; otherwise it is $(\texttt{addr}/128) \bmod 8$.

## Blackwell widens the field to three bits

The fifth-generation tensor core rewrites the descriptor. In the tcgen05 shared memory descriptor the start address grows to fifteen bits, the leading dimension offset grows to fifteen bits and gains a mode bit at position 52 selecting a relative offset or an absolute byte address, and the swizzle mode moves to bits 63 down to 61 and becomes three bits wide. The encoding is sparse and again non-monotone: 0 is no swizzling, 1 is 128-byte with 32-byte atomicity, 2 is 128-byte, 4 is 64-byte, 6 is 32-byte, and 3, 5 and 7 are invalid. CUTLASS names them `SWIZZLE_NONE`, `SWIZZLE_128B_BASE32B`, `SWIZZLE_128B`, `SWIZZLE_64B` and `SWIZZLE_32B`. Meanwhile the accumulator leaves shared memory entirely. On `sm_100a` the tensor memory is 128 lanes by 512 columns of 32-bit cells, that is $128 \times 512 \times 4 = 262144$ bytes per CTA, addressed by a 32-bit word carrying the lane index in bits 31 to 16 and the column index in bits 15 to 0. Nothing in that address space is swizzled; only the shared-memory operands are.

## Blackwell's 32-byte atom, and when it is mandatory

The new mode keeps the 128-byte span but makes the indivisible unit 32 bytes instead of 16, so the pattern is a $4 \times 4$ grid rather than $8 \times 8$. Row 0 holds 32-byte chunks $0,1,2,3$ and row 2 holds $2,3,0,1$; chunk $j$ of row $r$ sits at $r \oplus j$ with $r, j < 4$. In CuTe it is

$$\texttt{Swizzle<2,5,2>} \circ \big(\texttt{Shape<\_1024,\_4>}, \texttt{Stride<\_1,\_1024>}\big),$$

where base 5 means a $2^5 = 32$-byte atom, two bits means four phases, and shift 2 means four chunks. It exists only in the MN-major direction and needs 32-byte shared-memory alignment. It is not decoration: PTX's table of valid combinations says a 32-bit type in the transposed orientation, a column-major A or row-major B in tf32, supports only 128-byte swizzling with 32-byte atomicity, while 8-bit and 16-bit transposed operands support everything except it. Blackwell adds a 64-byte-atom variant, a $2 \times 2$ grid needing 64-byte alignment, and an eight-byte-flip variant legal only for cluster-scoped copies.

## Triton's vec, perPhase and maxPhase

Triton's older shared encoding describes the same family with three integers of its own. Element $(i,j)$ lands at

$$\left(\left(\left\lfloor \tfrac{i}{\texttt{perPhase}} \right\rfloor \bmod \texttt{maxPhase}\right) \oplus \left\lfloor \tfrac{j}{\texttt{vec}} \right\rfloor\right) \cdot \texttt{vec} \ \oplus\ (j \bmod \texttt{vec}),$$

so `vec` is the atom measured in elements, `perPhase` is how many consecutive rows share a phase, and `maxPhase` caps the XOR value. The compiler derives all three from the row width. With $K$ elements of `bitwidth` bits per row it sets $\texttt{perPhase} = \max(1024/(\texttt{bitwidth} \cdot K), 1)$, where 1024 is 1024 bits, one 128-byte bank sweep; then $\texttt{vec} = 4 \cdot \texttt{kWidth}$ with $\texttt{kWidth} = \max(32/\texttt{bitwidth}, 1)$. For fp16 with $K = 64$, a 128-byte row, that is $\texttt{perPhase} = 1$, $\texttt{vec} = 8$ elements or 16 bytes, and $\texttt{maxPhase} = \min(8, 1024/(8 \cdot 16)) = 8$. Halve the row to $K = 32$ and perPhase becomes 2 while maxPhase drops to 4, which is the 64-byte mode under another name.

## Triton's NVMMA encoding speaks hardware directly

For Hopper and Blackwell operands Triton stopped deriving parameters and started naming the hardware mode. `NVMMASharedEncodingAttr` stores a single `swizzlingByteWidth`, verified to be 0, 32, 64 or 128, and recovers the triple on demand:

$$\texttt{vec} = \frac{128}{\texttt{elementBitWidth}}, \quad \texttt{perPhase} = \frac{128}{W}, \quad \texttt{maxPhase} = \frac{W}{16}.$$

For bf16 at $W = 128$ that is vec 8, perPhase 1, maxPhase 8, the previous section's answer reached by another road; at $W = 64$ it is vec 8, perPhase 2, maxPhase 4; at $W = 32$, vec 8, perPhase 4, maxPhase 2. The mode itself comes from the contiguous extent in bytes, taking 128 if that extent is at least 128 and divisible by 128, else 64, else 32, else none. Two guards matter. If the flattened outer dimension is fewer than eight rows the swizzle is disabled entirely, because there is no eight-row atom to tile. And the buffer alignment is set to $128 \cdot \texttt{maxPhase}$, which is 1024 bytes at $W = 128$, so the descriptor's base offset is always zero.

## FlashAttention-3 and ThunderKittens in the field

Neither library invents a pattern. FlashAttention-3's Hopper mainloop builds its Q, K and V shared layouts from CUTLASS's `ss_smem_selector`, so a bf16 head dimension of 64 gets the 128-byte K-major atom, and it wraps K and V in `as_position_independent_swizzle_tensor` so the in-kernel transpose can use plain pointer arithmetic. Its pre-Hopper epilogue writes the swizzle by hand as `Swizzle<3,3,3>` over bf16 elements, where base 3 means eight bf16, that is 16 bytes, making it byte-identical to `Swizzle<3,4,3>`. ThunderKittens stores the choice in the tile type `st<T, rows, cols, swizzle, swizzle_bytes>` and evaluates it in one line:

```
return (T*)(addr ^ (((addr % (128*8)) >> 7) << 4));
```

which masks the address modulo 1024, extracts the row bits at position 7 and up, and XORs them in at bit 4: `Swizzle<3,4,3>` again. Its default is chosen by width, 128 bytes when a bf16 tile's column count is a multiple of 64, 64 bytes at a multiple of 32, 32 bytes otherwise.

## DeepGEMM simply refuses the 32-byte mode

A production kernel generator can be blunter than a library. DeepGEMM picks the mode with a four-way loop returning the first of 128, 64, 32, 16 that divides the inner block size in bytes, where 16 is labelled in the source as "actually non-swizzling, but interleaving". Its Hopper heuristic then discards any candidate configuration whose answer is not a multiple of 64, with the comment that 32-byte performance is low. The effect is a hard filter on tile shapes before anything is compiled. For bf16 with $\texttt{block\_k} = 64$ the inner size is $64 \times 2 = 128$ bytes and the mode is 128. For fp8 with $\texttt{block\_k} = 128$ it is again 128 bytes and again mode 128. A hypothetical $\texttt{block\_k} = 16$ in bf16 gives 32 bytes and the whole candidate is deleted. DeepGEMM also declines to swizzle fp32 outputs at all, and rounds its C and D shared buffers up to a multiple of 1024 bytes purely to satisfy TMA's swizzle alignment.

## Swizzling versus padding, counted in bytes

Padding still works, and it is still the wrong answer on Hopper for three separate reasons. First, memory. A $128 \times 64$ bf16 A-tile occupies $128 \times 64 \times 2 = 16384$ bytes. Pad each row by eight bf16 and it becomes $128 \times 72 \times 2 = 18432$ bytes, a 2048-byte or 12.5 percent tax. A four-stage pipeline holding one A-tile and one B-tile per stage grows from 128 KB to 144 KB, and an H100 SM has 228 KB of shared memory with a 227 KB per-block ceiling, so those 16 KB are half of a pipeline stage you no longer get. Second, alignment: `ldmatrix` needs every 16-byte row 16-byte aligned, and an eight-element bf16 pad preserves that only by luck of the number chosen. Third, and decisively, TMA has no destination pitch. A tensor map describes a dense box and the only remapping the engine can apply is the swizzle mode, so a padded shared layout cannot be the target of a bulk tensor copy at all.

## stmatrix, and the freedom that makes swizzling legal

Swizzling at 16-byte granularity is permitted only because the matrix instructions never assume rows are adjacent. PTX says of both `ldmatrix` and `stmatrix` that consecutive instances of a row need not be stored contiguously, and that the eight addresses for one $8 \times 8$ matrix are supplied by eight separate threads, each pointing at the start of one row. That is exactly the freedom the XOR consumes: it permutes whole 16-byte rows and never reorders bytes inside one. So `stmatrix.sync.aligned.m8n8.x4.shared.b16` writes an accumulator fragment straight into a swizzled tile with no extra arithmetic, which is part of why the article's output-swizzle experiment found nothing to gain on the C tile. On AMD the escape is different hardware rather than address freedom: CDNA4 adds a transposing LDS read that pulls a column-major tile out of shared memory in one instruction and hands it to the matrix core, deleting the access pattern that needed swizzling.

## Automatic layout synthesis: Hexcute and linear layouts

Two recent compilers stopped hand-picking modes. Hexcute factors a shared layout as $M = S \circ m$, where $m$ is a memory layout constrained by instruction alignment and $S$ is a swizzle that only permutes addresses. It solves for $m$ by type inference over layout constraints, then runs a pass that finds every copy touching a buffer, enumerates the applicable CuTe swizzle functions, and keeps the one minimising overlapping bank accesses within a warp. It reports matching cuBLAS and FlashAttention on GEMM and attention with 1.27 to 7.94 times less code than CUTLASS, and a 6.46 times average speedup over Triton on mixed-type mixture-of-experts operators. Linear layouts go further and make swizzling part of the type: since every memory layout is an invertible $\mathbb{F}_2$ matrix, the best swizzle becomes a subspace problem, choosing bases so distinct banks in distinct segments are touched by distinct threads. Integrated into Triton it cut shared-memory instructions for blocked reductions by 76 percent, from 5888 to 1388, and delivered up to 1.40 times on GH200.

## AMD: thirty-two banks, then sixty-four

The AMD analogue is the Local Data Share, and the bank count recently changed. On MI300, which is CDNA3, the LDS is 64 KB per compute unit split into 32 banks of four bytes, bank index $(\texttt{address}/4) \bmod 32$, giving 128 bytes per clock, exactly matching NVIDIA. On MI350X and MI355X, which are CDNA4, it grows to 160 KB with 64 banks of 640 four-byte entries, bank index $(\texttt{address}/4) \bmod 64$, and 256 bytes per clock. A wavefront is 64 lanes either way, so accesses split into phases: on MI300 a `ds_read_b128` takes eight phases of eight lanes, on MI350 four phases of sixteen. Composable Kernel's CK-Tile applies the XOR in coordinate space rather than on addresses,

$$K_0' = K_0 \oplus \left(M \bmod \frac{\texttt{KPerBlock}}{\texttt{Kpack}} \cdot \texttt{MLdsLayer}\right),$$

turning a two-way `ds_read_b128` conflict into none on a $64 \times 32$ fp16 A-tile. HipKittens uses the same shape of trick, `offset ^= ((offset % 512) >> 7) << 3`, which is CuTe's `Swizzle<2,3,4>`: an eight-byte atom over four rows of 128 bytes.

## When one swizzle is not enough

On NVIDIA a single swizzle per buffer suffices because every matrix instruction works in 16-byte rows. On AMD the granularity varies per instruction, and HipKittens gives a clean counterexample. A row-layout $16 \times 16$ bf16 tile written to LDS puts four bf16, that is 64 bits, in each thread, so the best store is `ds_write_b64` and a conflict-free pattern for it is the eight-byte-atom swizzle above. A row-layout $16 \times 32$ bf16 tile read back holds eight bf16 per thread, 128 bits, so the best load is `ds_read_b128`, which needs 128 contiguous bits in shared memory. The 64-bit swizzle has already broken memory into eight-byte pieces, so the two requirements are incompatible and no single pattern serves both. HipKittens' answer is to support swizzles that are conflict-free for layouts that commonly co-occur, and for global loads to swizzle the HBM addresses instead, because AMD's direct global-to-LDS path takes per-thread source addresses rather than a tensor map.

## A number-theoretic alternative to the XOR

XOR is not the only bijection that spreads a column across banks, and for non-tensor-core workloads it is not always the best one. The 2025 SPAA result on GPU mergesort eliminates all bank conflicts using coprimality rather than bit arithmetic: if a warp's threads access shared memory at stride $E$ with $\gcd(E, w) = 1$ for $w = 32$ banks, the addresses form a complete residue system modulo $w$ and every thread hits a different bank. The hard case is $d = \gcd(w, E) > 1$, where every $w/d$-th element collides, and the paper constructs an explicit permutation restoring the residue system. On worst-case inputs on an RTX 2080 Ti the conflict-free merge gives average, median and maximum speedups of 1.37, 1.45 and 1.47 at $E = 15$, and 1.17, 1.23 and 1.25 at $E = 17$, while matching stock Thrust on random inputs. The trade-off is exact: coprime strides need no power-of-two shape, but no hardware descriptor can express them, so no DMA engine will do them for you.

## Open problems

Three gaps are visible from the specifications alone. First, granularity: the hardware fixes one atom size per buffer, but a tile written at eight-byte granularity and read at sixteen may admit no common swizzle, which on AMD forces per-instruction patterns and on NVIDIA forces tile shapes chosen for the swizzle rather than for the mathematics. Second, the odd modes are undocumented territory. PTX defines a 96-byte swizzle whose pattern repeats on a 256-byte boundary with base offset $(\texttt{addr}/128) \bmod 2$, but the driver API exposes it only through the wide im2col path, and narrow types are heavily restricted: the six-bit-in-sixteen format permits only the none, 128-byte and 128-byte-32-byte-atom modes. Third, nobody has published a measurement isolating Blackwell's 32-byte atom against the 16-byte atom, even though PTX makes it mandatory for transposed tf32. The mathematics, at least, is settled: each of these is a shear $M = I + E$ over $\mathbb{F}_2$, and the open question is only which $E$ the silicon agrees to compute.
