# Attention Is All You Need: key equations (companion to the talk transcript)

## Scaled dot-product attention

$$
\mathrm{Attention}(Q, K, V) = \mathrm{softmax}\!\left(\frac{QK^{\top}}{\sqrt{d_k}}\right) V
$$

The queries and keys are compared by dot product, scaled by the square root of the key dimension so the softmax does not saturate for large dimensions, and the resulting weights mix the value vectors.

## Multi-head attention

$$
\mathrm{MultiHead}(Q, K, V) = \mathrm{Concat}(\mathrm{head}_1, \ldots, \mathrm{head}_h) W^{O}, \qquad \mathrm{head}_i = \mathrm{Attention}(Q W_i^{Q}, K W_i^{K}, V W_i^{V})
$$

Each head projects the inputs into a lower-dimensional subspace and attends there, so different heads can attend to different kinds of relationships in parallel.

## Position-wise feed-forward layer

$$
\mathrm{FFN}(x) = \max(0, x W_1 + b_1) W_2 + b_2
$$

The same two-layer network is applied to every position independently.
