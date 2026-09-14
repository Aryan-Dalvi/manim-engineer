# Swizzling explained properly: equation sheet

### swizzle_bijection

$$
f(r, c) = (r,\; c \oplus r)
$$

### same_row_distinct

$$
(c \oplus r) \oplus (c' \oplus r) = c \oplus c' \neq 0 \quad \text{for } c \neq c'
$$

### same_column_distinct

$$
(c \oplus r) \oplus (c \oplus r') = r \oplus r' \neq 0 \quad \text{for } r \neq r'
$$

### xor_facts

$$
a \oplus b = 0 \iff a = b, \qquad a \oplus a = 0, \qquad (a \oplus b) \oplus c = a \oplus (b \oplus c)
$$

### bijection_bound

$$
M = 2^a,\; N = 2^b,\; a \le b \;\Rightarrow\; c \oplus r \le N - 1
$$

### bank_of_address

$$
\text{bank}(\text{addr}) = \left\lfloor \frac{\text{addr}}{4} \right\rfloor \bmod 32
$$

### smem_peak_bandwidth

$$
4\ \text{B/bank/cycle} \times 32\ \text{banks} = 128\ \text{B/cycle}
$$

### raster_offset_bits

$$
\text{offset}(r, c) = r \cdot N + c = (r \ll \log_2 N) \mid c
$$

### cute_swizzle

$$
\text{Swizzle}\langle B, M, S\rangle(x) = x \oplus \Big(\big(x \,\&\, (\,(2^B - 1) \ll (M + S)\,)\big) \gg S\Big)
$$

### swizzle_modes

$$
\text{Swizzle 32B} = \text{Swizzle}\langle 1, 4, 3\rangle,\quad \text{Swizzle 64B} = \text{Swizzle}\langle 2, 4, 3\rangle,\quad \text{Swizzle 128B} = \text{Swizzle}\langle 3, 4, 3\rangle
$$

### conflict_degree_by_mode

$$
\text{conflict degree} = \frac{8}{2^{\text{bits}}}: \quad 8 \to 4 \to 2 \to 1 \text{ for none, 32B, 64B, 128B}
$$

### gmem_to_smem_reloads

$$
\frac{8192}{128} = 64,\qquad 64 \times 8192^2 \times 2\ \text{B} \times 2 = 17.18\ \text{GB}
$$

### loads_vs_stores

$$
\frac{\text{SMEM loads}}{\text{SMEM stores}} = \frac{(2 + 4) \times 2\ \text{B}}{4\ \text{B}} = 3 \quad (51.81\ \text{GB vs } 17.45\ \text{GB})
$$

### c_tile_store_share

$$
8192^2 \times 4\ \text{B} = 268\ \text{MB} \approx 1.5\% \text{ of } 17.45\ \text{GB}
$$
