"""Interactive Activation and Competition (IAC) network.

After McClelland & Rumelhart, "Explorations in Parallel Distributed
Processing" (the `iac` model, ch. 2). Units are grouped into pools. Units in
different pools are joined by symmetric excitatory weights; units inside a
competitive pool inhibit each other. On each cycle, for unit i:

    net_i = estr * ext_i + alpha * sum_j w_ij * o_j - gamma * sum_{k in pool(i), k != i} o_k
    o_j   = max(0, a_j)

    net_i > 0:  da_i = (max - a_i) * net_i - decay * (a_i - rest)
    net_i <= 0: da_i = (a_i - min) * net_i - decay * (a_i - rest)

and the network is cycled until it settles.
"""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Params:
    max: float = 1.0
    min: float = -0.2
    rest: float = -0.1
    decay: float = 0.1
    estr: float = 0.4    # scale of external input
    alpha: float = 0.1   # scale of excitatory input from other units
    gamma: float = 0.1   # scale of within-pool inhibition
    max_cycles: int = 300
    tol: float = 1e-4


@dataclass
class Result:
    activation: np.ndarray
    cycles: int
    settled: bool


def net_input(weights, pools, ext, out, p):
    """Net input to every unit given the current outputs.

    pools: [(slice, gamma_scale)] - gamma_scale 0 means the pool does not compete.
    """
    inhibition = np.zeros_like(out)
    for sl, scale in pools:
        if scale:
            pool_out = out[sl]
            inhibition[sl] = scale * (pool_out.sum() - pool_out)
    return p.estr * ext + p.alpha * (weights @ out) - p.gamma * inhibition


def settle(weights, pools, ext, params=Params()):
    """Cycle the network from rest until activations stop changing."""
    p = params
    a = np.full(len(ext), p.rest, dtype=np.float64)
    cycles, settled = 0, False
    for cycles in range(1, p.max_cycles + 1):
        net = net_input(weights, pools, ext, np.maximum(a, 0.0), p)
        delta = np.where(net > 0, (p.max - a) * net, (a - p.min) * net) - p.decay * (a - p.rest)
        a = np.clip(a + delta, p.min, p.max)
        if np.abs(delta).max() < p.tol:
            settled = True
            break
    return Result(a, cycles, settled)


def luce_choice(activations, k=10.0, null=0.0):
    """Luce choice rule over positively active units plus a 'none of these' unit.

    Returns (probabilities, p_none); probabilities are 0 for units at or below `null`.
    """
    a = np.asarray(activations, dtype=np.float64)
    strength = np.where(a > null, np.exp(k * (a - null)), 0.0)
    total = strength.sum() + 1.0  # the null unit has strength exp(0) = 1
    return strength / total, 1.0 / total
