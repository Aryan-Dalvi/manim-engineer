# Softmax temperature

Softmax turns a vector of logits into a probability distribution. Every entry is positive and the entries sum to one, so the output can be read as "how likely is each class".

$$
p_i = \frac{e^{z_i}}{\sum_j e^{z_j}}
$$

A temperature parameter T divides the logits before the exponential. This one knob changes how peaked the distribution is without changing the ordering of the classes.

$$
p_i(T) = \frac{e^{z_i / T}}{\sum_j e^{z_j / T}}
$$

As T goes to zero the largest logit wins everything and the distribution becomes a one-hot spike, which is greedy decoding. As T grows large every logit is divided by a huge number, the exponentials become nearly equal, and the distribution flattens toward uniform. At T equal to one you recover plain softmax.

This is the knob behind sampling diversity in language models. Sampling at low temperature repeats the most likely continuation; sampling at high temperature makes rare tokens more likely and the text more surprising. The trade-off is sharpness against coverage, and the picture to hold in mind is a bar chart of probabilities that either spikes or spreads as T moves.
