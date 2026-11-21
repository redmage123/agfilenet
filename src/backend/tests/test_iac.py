import numpy as np

from agfilenet import iac


def network():
    """Two instance units (0, 1) competing; three property units (2, 3, 4).

    Instance 0 has properties 2 and 3; instance 1 has properties 3 and 4.
    """
    w = np.zeros((5, 5))
    for a, b in ((0, 2), (0, 3), (1, 3), (1, 4)):
        w[a, b] = w[b, a] = 1.0
    return w, [(slice(0, 2), 1.0), (slice(2, 5), 0.0)]


def test_rests_without_input():
    w, pools = network()
    result = iac.settle(w, pools, np.zeros(5))
    assert result.settled
    assert np.allclose(result.activation, iac.Params().rest)


def test_settles_and_activation_stays_in_bounds():
    w, pools = network()
    p = iac.Params()
    assert iac.settle(w, pools, np.array([0, 0, 1.0, 1.0, -1.0])).settled
    result = iac.settle(w, pools, np.array([0, 0, 50.0, 50.0, -50.0]))  # absurdly strong input
    assert result.activation.max() <= p.max and result.activation.min() >= p.min


def test_probe_retrieves_instance_and_fills_in_its_other_property():
    w, pools = network()
    a = iac.settle(w, pools, np.array([0, 0, 1.0, 0, 0])).activation
    assert a[0] > 0.3                    # the instance with the probed property wins
    assert a[0] > a[1]                   # and beats its competitor
    assert a[3] > 0                      # pattern completion: its other property becomes active
    assert a[3] > a[4]                   # more than the property only the loser has


def test_competition_suppresses_the_weaker_instance():
    w, pools = network()
    ext = np.array([0, 0, 1.0, 1.0, 0.2])
    with_competition = iac.settle(w, pools, ext).activation
    without = iac.settle(w, [(slice(0, 2), 0.0), (slice(2, 5), 0.0)], ext).activation
    assert with_competition[1] < without[1]


def test_luce_choice_sums_to_one_with_null():
    p, p_none = iac.luce_choice(np.array([0.8, 0.3, -0.1]))
    assert abs(p.sum() + p_none - 1) < 1e-9
    assert p[0] > p[1] > 0 and p[2] == 0
    assert iac.luce_choice(np.array([-0.1, -0.1]))[1] == 1.0
