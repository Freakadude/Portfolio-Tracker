"""NFR-03: building an analytics context pauses the cyclic collector and keeps the result out of
its reach, and always leaves the collector as it found it."""

import gc

import pytest

from folio.analytics_service import _build_without_gc


def test_the_collector_is_paused_during_a_build_and_back_on_after() -> None:
    assert gc.isenabled()
    before = gc.get_freeze_count()
    with _build_without_gc():
        assert not gc.isenabled()
        junk = [[n] for n in range(1000)]
    assert gc.isenabled() and gc.get_freeze_count() >= before + len(junk)


def test_a_failed_build_still_restores_the_collector() -> None:
    with pytest.raises(RuntimeError), _build_without_gc():
        raise RuntimeError("the build failed")
    assert gc.isenabled()


def test_a_collector_that_was_off_stays_off() -> None:
    gc.disable()
    try:
        with _build_without_gc():
            pass
        assert not gc.isenabled()
    finally:
        gc.enable()
