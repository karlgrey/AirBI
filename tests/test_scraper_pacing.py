import random

from airbi.scraper.pacing import human_delay, pick_delay


def test_pick_delay_stays_within_bounds():
    rng = random.Random(42)
    for _ in range(200):
        d = pick_delay(0.5, 2.0, rng=rng)
        assert 0.5 <= d <= 2.0


def test_pick_delay_is_deterministic_with_seeded_rng():
    assert pick_delay(0.5, 2.0, rng=random.Random(1)) == pick_delay(
        0.5, 2.0, rng=random.Random(1)
    )


def test_human_delay_sleeps_for_the_picked_duration():
    slept = []
    duration = human_delay(0.1, 0.2, rng=random.Random(7), sleeper=slept.append)
    assert 0.1 <= duration <= 0.2
    assert slept == [duration]
