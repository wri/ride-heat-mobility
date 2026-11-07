from __future__ import annotations

import numpy as np
import pandas as pd


class _Accumulator:
    """Running sums keyed by an integer-tuple id, plus the distinct agents seen per id."""

    def __init__(self, key_width: int) -> None:
        self.key_width = key_width
        self.ids: dict[tuple, int] = {}
        self.heat: list[float] = []
        self.minutes: list[float] = []
        # (id, agent) pairs seen, kept as int64 codes and de-duplicated in chunks so
        # memory stays ~one entry per (segment, agent) actually used.
        self._pairs: list[np.ndarray] = []
        self._pairs_len = 0
        self._tracks_agents = False

    def add(self, keys: np.ndarray, heat: np.ndarray, minutes, agents: np.ndarray | None) -> None:
        """minutes: per-row minutes (array), or one value for every row."""
        if len(keys) == 0:
            return
        uniq, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.ravel()
        heat_sum = np.bincount(inv, weights=heat, minlength=len(uniq))
        mins = np.broadcast_to(np.asarray(minutes, dtype=float), inv.shape)
        min_sum = np.bincount(inv, weights=mins, minlength=len(uniq))
        local_ids = np.empty(len(uniq), dtype=np.int64)
        for j, (key, h, m) in enumerate(zip(map(tuple, uniq.tolist()), heat_sum.tolist(), min_sum.tolist())):
            i = self.ids.get(key)
            if i is None:
                i = self.ids[key] = len(self.heat)
                self.heat.append(0.0)
                self.minutes.append(0.0)
            self.heat[i] += h
            self.minutes[i] += m
            local_ids[j] = i
        if agents is not None:
            self._tracks_agents = True
            self._pairs.append((local_ids[inv] << 32) | agents.astype(np.int64))
            self._pairs_len += len(inv)
            if self._pairs_len > 2_000_000:
                self._compact()

    def _compact(self) -> np.ndarray:
        pairs = np.unique(np.concatenate(self._pairs)) if self._pairs else np.zeros(0, dtype=np.int64)
        self._pairs, self._pairs_len = [pairs], len(pairs)
        return pairs

    def n_persons(self) -> np.ndarray:
        """Distinct agents per id (NaN everywhere if agents were never passed)."""
        if not self._tracks_agents:
            return np.full(len(self.heat), np.nan)
        return np.bincount(self._compact() >> 32, minlength=len(self.heat)).astype(np.float64)

    def frame(self, key_names: list[str]) -> pd.DataFrame:
        keys = np.array(list(self.ids), dtype=np.int64).reshape(-1, self.key_width)
        order = np.array(list(self.ids.values()), dtype=np.int64)
        df = pd.DataFrame({name: pd.Series(keys[:, j], dtype="int64") for j, name in enumerate(key_names)})
        df["heat_degC_min"] = np.asarray(self.heat, dtype=np.float64)[order]
        df["person_min"] = np.asarray(self.minutes, dtype=np.float64)[order]
        df["n_persons"] = self.n_persons()[order]
        return df


class SegmentExposure:
    """
    Running totals of outdoor heat exposure (°C·min of UTCI above the threshold, see
    scheduler.tick), person-minutes and distinct people,
    attributed to where they happened:

    - walking agents -> the directed graph edge (u, v, key) they are on;
    - agents waiting to board transit -> the stop node they are standing at (edge_u).

    In-vehicle transit riding is never added (matches AgentPool.heat_exposure_degC_min),
    so summed over edges + stops this equals the sum of all agents' exposure.

    scheduler.tick() splits each tick into the time spent on each edge or stop, so
    person_min is real time spent there. n_persons counts each agent once per edge (or
    stop) however long it spent there, so heat_degC_min / n_persons is the mean
    exposure one person picked up on that segment.

    Updated once per tick by scheduler.py::tick() with vectorised per-tick group sums.
    """

    def __init__(self) -> None:
        self._edges = _Accumulator(3)
        self._stops = _Accumulator(1)

    def add_edges(
        self, u: np.ndarray, v: np.ndarray, key: np.ndarray, heat: np.ndarray, minutes,
        agents: np.ndarray | None = None,
    ) -> None:
        keys = np.column_stack([u.astype(np.int64), v.astype(np.int64), key.astype(np.int64)])
        self._edges.add(keys, heat, minutes, agents)

    def add_stops(self, nodes: np.ndarray, heat: np.ndarray, minutes, agents: np.ndarray | None = None) -> None:
        self._stops.add(nodes.astype(np.int64).reshape(-1, 1), heat, minutes, agents)

    def edges_frame(self) -> pd.DataFrame:
        """One row per directed edge used: u, v, key, heat_degC_min, person_min, n_persons."""
        return self._edges.frame(["u", "v", "key"])

    def stops_frame(self) -> pd.DataFrame:
        """One row per stop where someone waited: node, heat_degC_min, person_min, n_persons."""
        return self._stops.frame(["node"])
