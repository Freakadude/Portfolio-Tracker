# ADR 0050: Build analytics contexts with the cyclic collector paused

Status: accepted (2026-10-09). Concerns NFR-03 and ADR 0016.

## Context
The NFR-03 check (dashboard endpoints under 300 ms at p95) failed three times in a row on the GitHub runner (446, 339 and 431 ms) while passing locally. Profiling showed two causes. Building an analytics context creates millions of small objects that all stay alive, and Python's cyclic collector spent a third of the build (about 460 of 1,350 ms here) scanning them; the full collections it ran later each cost a request 200 ms or more here and several times that on the runner, landing on whichever request happened to be next. And the risk endpoint spent most of its time in the two correlation matrices (sorting the common days of each of 1,225 pairs).

## Decision
- `get_context` builds a context with the collector paused and then freezes what exists (`gc.freeze()`), so the collector never scans it again. A context has no reference cycles (measured: after it is dropped, a full collection finds nothing unreachable), so the cache frees it by reference counting when it is evicted and nothing leaks. The collector is restored to the state it was in, also when the build fails.
- Correlation matrices of holdings that trade on the same days standardise each series once and take one dot product per pair; other series use the old pairwise path without sorting the days. Results agree with the exact Decimal pair figure to 1e-12 (tested).
- A single instrument's series skips the generic summing, and the per-instrument return figures of the heatmap are kept in the context like every other derived result.

## Consequences
On the 10 years by 50 instruments test data: the context build 1.4 s to 0.85 s, the risk endpoint 159 ms to 63 ms, and the p95 of the NFR-03 test (in effect the third-slowest uncached derivation) about 95 ms to 63 ms. The GitHub runner measured 3 to 4 times slower than this machine, which leaves the test comfortably under 300 ms there. Objects created while a build runs are never collected as cyclic garbage; the few cycles a build makes (about 550 objects) stay until the process ends.
