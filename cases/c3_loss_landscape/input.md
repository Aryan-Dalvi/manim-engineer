# Gradient descent on a loss landscape

## The update rule

Training a model means finding parameters that make a loss function small. Gradient descent does this by repeatedly stepping against the gradient, the direction of steepest increase, scaled by a learning rate.

$$
\theta_{t+1} = \theta_t - \eta \nabla_\theta L(\theta_t)
$$

The learning rate eta controls the step size. A rate that is too small crawls toward the minimum and takes forever; a rate that is too large overshoots the valley and can diverge. The picture is a ball rolling down a bowl-shaped surface, taking discrete hops instead of sliding.

## Why the curvature matters

Consider a one-dimensional quadratic loss with curvature a. The update multiplies the distance from the minimum by a constant factor each step.

$$
L(\theta) = \tfrac{1}{2} a \theta^2, \qquad \theta_{t+1} = (1 - \eta a)\,\theta_t
$$

If eta times a is between zero and one the distance shrinks monotonically. Between one and two it overshoots but still converges, bouncing across the minimum with shrinking amplitude. Above two the bounces grow and training diverges. So the stable learning rate is bounded by two over the curvature, and sharp directions of the loss surface set the limit for the whole optimizer.

## Momentum

Momentum keeps a running velocity that accumulates past gradients, so the optimizer keeps moving through flat regions and damps the zig-zag across steep valleys.

$$
v_{t+1} = \beta v_t + \nabla_\theta L(\theta_t), \qquad \theta_{t+1} = \theta_t - \eta v_{t+1}
$$

With beta near 0.9 the velocity averages roughly the last ten gradients. Along a long shallow valley the components of the gradient that keep pointing the same way add up and the optimizer accelerates; across the valley walls the components alternate sign and cancel. That is why momentum reaches the bottom of an elongated bowl in far fewer steps than plain gradient descent.
