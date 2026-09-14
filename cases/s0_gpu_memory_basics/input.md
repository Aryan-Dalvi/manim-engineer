# Before You Read About Swizzling

## Grid, Thread Block, Warp, Thread

A CUDA launch builds a four-level tree. You write code for one thread; the hardware groups 32 consecutive threads into a warp, groups warps into a thread block, and groups thread blocks into a grid. The CUDA Programming Guide is blunt about the middle level: threads are organized into groups of 32 called warps, and a warp executes one common instruction at a time. The partitioning is fixed, never negotiated: the first warp always holds threads 0 through 31, the second holds 32 through 63.

Take the matmul kernel the swizzling article benchmarks. It multiplies two $8192 \times 8192$ matrices using $128 \times 128$ output tiles, so the grid is

$$\frac{8192}{128} \times \frac{8192}{128} = 64 \times 64 = 4096 \text{ thread blocks}$$

Each block runs 256 threads, which is exactly 8 warps, since $256 / 32 = 8$. Multiply it out and the launch describes $4096 \times 256 = 1{,}048{,}576$ threads, organized as $32{,}768$ warps. Every statement about bank conflicts later is a statement about one of those warps.

## The Streaming Multiprocessor

A grid does not run all at once. Thread blocks are handed to Streaming Multiprocessors, or SMs, which are the physical cores of the GPU. An A100 has 108 SMs; an H100 SXM5 has 132. Each SM owns a register file, a block of shared memory, warp schedulers, and arithmetic pipelines, and it owns nothing else. Shared memory belongs to a thread block on one SM, which is why two blocks can never see each other's tiles.

Residency has hard ceilings. On compute capability 8.0, an SM holds at most 2048 threads, at most 64 warps, at most 32 thread blocks, and at most 65,536 32-bit registers. Our 4096-block launch therefore does not run 4096 blocks simultaneously; if each block used 64 KB of the 164 KB shared memory available, only two blocks fit per SM, so at most $108 \times 2 = 216$ blocks are live and the remaining 3880 queue up behind them. Switching between resident warps is free, because every warp's registers stay on chip for its whole lifetime.

## Sizes and Bandwidths of the Memory Hierarchy

Four tiers sit between an arithmetic unit and DRAM, each roughly an order of magnitude larger and slower than the one above it. On an A100 the register file is 256 KB per SM, which is 65,536 registers of 32 bits. Shared memory and L1 share a 192 KB block per SM, of which up to 164 KB can be carved out as shared memory. L2 is 40 MB for the whole chip. Global memory is 40 or 80 GB of HBM2.

Bandwidth moves the same way. Shared memory delivers 32 banks times 4 bytes per clock, which is 128 bytes per clock per SM; across 108 SMs at 1.41 GHz that is about 19.5 TB/s. L2 reads at 5120 bytes per clock, about 7.2 TB/s. HBM2 on the A100 whitepaper part delivers 1555 GB/s, and the 80 GB PCIe card reaches 1.94 TB/s. So shared memory is roughly ten times faster than global memory, and registers, which feed three operands per lane per clock, are on the order of 100 TB/s.

## Latency Is Where the Orders of Magnitude Live

Bandwidth tells you how much arrives per second; latency tells you how long the first byte takes. Microbenchmarks on an A100 measure the four tiers as follows. A shared memory access completes in about 29 clock cycles. An L1 hit takes about 38. An L2 hit takes about 262. A global memory access that misses everything takes about 466. A dependent arithmetic instruction such as an FMA resolves in 4 cycles.

Line those up and the span is stark:

$$4 \to 29 \to 38 \to 262 \to 466 \text{ cycles}$$

Global memory is $466 / 4 \approx 116$ times slower than a register, and $466 / 29 \approx 16$ times slower than shared memory. At 1.41 GHz, 466 cycles is 330 nanoseconds, during which the SM could have retired more than a hundred dependent FMAs. This is the whole reason a GPU keeps 64 warps resident per SM: while one warp waits 466 cycles, the scheduler issues from the other 63.

## Cache Lines, Sectors, Hits and Misses

Memory is not fetched one byte at a time. Both L1 and L2 store data in 128-byte cache lines, and each line is divided into four 32-byte sectors. A hit means the sector you asked for is already resident and you pay the cache's latency. A miss means the hardware goes down a level and you pay that level's latency instead.

Watch what this does to a single thread walking an array of floats. It reads address 0, misses everything, and waits roughly 466 cycles while the 32-byte sector containing addresses 0 through 31 arrives. Now it reads addresses 4, 8, 12, up to 28: seven more floats, all in that same sector, each an L1 hit at roughly 38 cycles. The first access cost 466 and the next seven cost 38 apiece, so eight floats arrived in about $466 + 7 \times 38 = 732$ cycles instead of $8 \times 466 = 3728$. Locality is worth a factor of five here purely because the line was already paid for.

## Coalesced Versus Strided Global Loads

A warp issues one load instruction with 32 addresses. The hardware coalesces those into as few 32-byte transactions as it can, and the ratio of bytes used to bytes moved is what you are optimizing.

Consider the good case first. Thirty-two threads each read a 4-byte float at addresses 0, 4, 8, and so on to 124. That is 128 contiguous bytes, served by exactly four 32-byte transactions, and every byte fetched is a byte someone wanted. Utilization is 100%.

Now stride the same warp by 32 floats, so thread $i$ reads address $128i$: addresses 0, 128, 256, up to 3968. No two threads share a 32-byte segment, so the warp issues 32 separate transactions and moves

$$32 \times 32 = 1024 \text{ bytes to deliver } 32 \times 4 = 128 \text{ useful bytes}$$

That is $128/1024 = 12.5\%$ utilization, an eightfold waste of bandwidth. Threads do not have to be in address order to coalesce; any permutation within the same 32-byte segments works equally well.

## Shared Memory Banks and the Bank Formula

Shared memory is not a flat array. It is 32 independent banks, each serving 32 bits per clock cycle, with successive 32-bit words mapped to successive banks. The bank holding a given byte address is therefore

$$\text{bank} = \left\lfloor \frac{\text{byte address}}{4} \right\rfloor \bmod 32$$

which, because 4 and 32 are powers of two, is just bits 6 down to 2 of the address. Byte 4100 sits in word $4100/4 = 1025$, and $1025 \bmod 32 = 1$, so bank 1. In binary, 4100 is 1000000000100, whose bits 6:2 read 00001. Same answer, no division.

Two consequences follow immediately. Addresses repeat their bank every 128 bytes, since $128/4 = 32$. And the total shared memory bandwidth is 4 bytes per bank per cycle times 32 banks, which is 128 bytes per cycle per SM, exactly one full row of banks.

## Bank Conflicts Serialize a Warp

Each bank serves one word per cycle. When two threads of a warp want different words from the same bank, the hardware has no choice but to serialize them, and an $n$-way conflict occupies that bank for $n$ cycles.

The CUDA guide's own example is the cleanest picture. Declare a shared array of 32 by 32 floats and launch a 32 by 32 thread block. When warp 0 reads a row, threads touch addresses 0, 4, 8, up to 124. Those are banks 0 through 31, all distinct, and the whole row arrives in one cycle at the full 128 bytes per cycle.

Now have warp 0 read a column instead. Consecutive threads are 32 floats, or 128 bytes, apart, so they read addresses 0, 128, 256, up to 3968. Every one of those maps to bank 0:

$$\frac{128i}{4} \bmod 32 = 32i \bmod 32 = 0$$

That is a 32-way conflict. One column takes 32 cycles and delivers 4 bytes per cycle instead of 128.

## The Broadcast Exception

There is one escape hatch, and it is not a conflict at all. If several threads of a warp read the exact same shared memory address, the hardware broadcasts that word to all of them in a single cycle. The rule is about distinct words within a bank, not about threads per bank.

The distinction matters. Suppose all 32 threads read address 0. Naively that is 32 requests to bank 0, which sounds like a 32-way conflict and 32 cycles. In fact it is one word, broadcast, and it finishes in one cycle. Now suppose instead that 16 threads read address 0 and 16 threads read address 128. Both addresses live in bank 0, but they are two different words, so bank 0 must serve them on two separate cycles: a 2-way conflict, not a 32-way one, and not a broadcast either.

For writes the rule is weaker. If several threads write the same address, exactly one write survives, and which thread wins is undefined.

## Tiling a Matmul Through Shared Memory

Shared memory is small, so matrix multiplication is restructured to reuse it. The matrices in the swizzling article are $8192 \times 8192$ in FP16, which is

$$8192 \times 8192 \times 2 \text{ bytes} = 134.2 \text{ MB each}$$

Nothing that size goes into 164 KB of shared memory. So each thread block claims a $128 \times 128$ output tile and marches along $k$ in steps of 64, staging a $128 \times 64$ slab of $A$ and a $128 \times 64$ slab of $B$ into shared memory. Each slab is $128 \times 64 \times 2 = 16$ KB, so both fit in 32 KB.

The payoff is reuse. Every element loaded into that $A$ slab is used by all 128 output columns of the tile, so instead of reading each element of $A$ from global memory 8192 times, the kernel reads it $8192/128 = 64$ times. That is a 128-fold cut in global traffic, from roughly 2.2 TB down to 17.2 GB. All the bank conflicts we care about happen inside those staged tiles.

## What mma.m16n8k8 Expects From a Warp

Tensor cores do not take matrices; they take fragments spread across a warp's registers. The PTX instruction `mma.sync.aligned.m16n8k8` multiplies a $16 \times 8$ matrix $A$ by an $8 \times 8$ matrix $B$ into a $16 \times 8$ accumulator, and every one of the 32 lanes must be holding exactly the right elements.

Count them. $A$ has $16 \times 8 = 128$ FP16 elements, so each lane holds 4, packed into two 32-bit registers. $B$ has 64 elements, so each lane holds 2 in one register. The FP32 accumulator has 128 elements, so each lane holds 4 floats.

The mapping is pure bit arithmetic on the lane index. PTX defines $\text{groupID} = \text{lane} \gg 2$ and $\text{tid} = \text{lane} \bmod 4$, and then the accumulator rows are $\text{groupID}$ and $\text{groupID} + 8$ while the columns are $2 \cdot \text{tid}$ and $2 \cdot \text{tid} + 1$. Lane 5 gives groupID 1 and tid 1, so lane 5 holds $C_{1,2}$, $C_{1,3}$, $C_{9,2}$ and $C_{9,3}$.

## ldmatrix Loads Eight Rows of Sixteen Bytes

Shuffling data into that fragment layout by hand would be miserable, so PTX provides `ldmatrix`, a warp-wide shared memory load that does the rearrangement in hardware. Its `.m8n8` shape loads an 8 by 8 matrix of 16-bit elements, so one row is $8 \times 2 = 16$ bytes and the whole matrix is 128 bytes.

The crucial detail is how addresses are supplied. Threads 0 through 7 each hand the instruction one address, and each address is the start of one row. PTX states plainly that consecutive instances of a row need not be stored contiguously in memory, and that a group of four consecutive threads loads 16 bytes, so matrix addresses must be naturally aligned to 16 bytes.

Read that twice, because it is the licence swizzling exploits. The eight 16-byte rows may sit anywhere in shared memory, in any order, so long as each row's own 16 bytes stay together and stay 16-byte aligned. You may move whole rows; you may not stir the bytes inside one.

## Powers of Two and Row-Major Offsets as Bit Concatenation

An index that runs from 0 to $N-1$ needs $\log_2 N$ bits when $N$ is a power of two. Eight columns need 3 bits, four rows need 2 bits, 32 banks need 5 bits. This is why swizzling insists on power-of-two dimensions: it lets index arithmetic become bit-field surgery.

In a row-major grid of 4 rows and 8 columns, element $(r, c)$ sits at raster offset $8r + c$. Because 8 is $2^3$, that multiply is a shift and the add is an or:

$$\text{offset} = 8r + c = (r \ll 3) \mathbin{|} c$$

So the offset is literally the row bits concatenated with the column bits. Take $r = 2 = 10_2$ and $c = 5 = 101_2$. The offset is $10101_2 = 21$, and indeed $8 \times 2 + 5 = 21$. Reading the 5-bit offset back, the top 2 bits recover the row and the bottom 3 recover the column. Permuting a matrix's layout is now just rewriting selected bits of an offset.

## The Three XOR Facts That Make Swizzling Work

Bitwise XOR, written $\oplus$, compares two numbers bit by bit and emits 1 where they differ. Three properties carry the entire swizzling argument.

First, it is self-inverse: $a \oplus a = 0$ and $a \oplus 0 = a$, so $(a \oplus b) \oplus b = a$. Second, it is commutative and associative, so you may reorder and regroup freely. Third, and decisively, $a \oplus b = 0$ if and only if $a = b$, since a bit position can only cancel when both inputs agree there.

Put them together and XOR by a fixed value is a bijection. If $c \oplus r = c' \oplus r$, then XOR both sides by the left one:

$$(c \oplus r) \oplus (c' \oplus r) = c \oplus c' = 0 \implies c = c'$$

Concretely, $5 \oplus 3$ is $101_2 \oplus 011_2 = 110_2 = 6$, and $6 \oplus 3 = 110_2 \oplus 011_2 = 101_2 = 5$ again. One more fact for later: if $c < 2^b$ and $r < 2^b$, then $c \oplus r < 2^b$, because XOR never sets a bit neither operand had.

## The Conflict Swizzling Actually Fixes

Now assemble everything on the article's real tile. The $A$ slab in shared memory is 128 rows of 64 FP16 values, so one row is $64 \times 2 = 128$ bytes: exactly 32 words, the full bank width.

That coincidence is fatal. Row $r$ begins at byte $128r$, so its bank is

$$\left\lfloor \frac{128r}{4} \right\rfloor \bmod 32 = 32r \bmod 32 = 0$$

Every row starts at bank 0. When `ldmatrix` asks for eight rows at the same column offset, all eight 16-byte requests hit the same four banks: an 8-way conflict, eight cycles where one would do, 16 bytes per cycle out of 128.

Padding each row to 136 bytes fixes it but breaks the 16-byte alignment `ldmatrix` demands. The alternative is to permute which column each row's chunk lands in, using the map $f(r, c) = (r, c \oplus r)$. On a 4 by 4 grid, row 0 reads columns 0,1,2,3; row 1 reads 1,0,3,2; row 2 reads 2,3,0,1; row 3 reads 3,2,1,0. Every row is still a permutation of all four columns, and every column now draws from four different rows, so no two collide. No padding, no bytes moved within a row. That is swizzling.
