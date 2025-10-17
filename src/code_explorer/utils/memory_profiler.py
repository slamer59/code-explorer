"""Simple memory profiling with tracemalloc (built-in, zero dependencies)"""
import tracemalloc
import os
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class MemorySnapshot:
    """A memory snapshot at a specific checkpoint"""
    name: str
    current_mb: float
    peak_mb: float


class MemoryProfiler:
    """Lightweight memory profiler using tracemalloc"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.snapshots: List[MemorySnapshot] = []
        self.start_memory = 0.0

        if self.enabled:
            tracemalloc.start()

    def snapshot(self, name: str) -> Optional[MemorySnapshot]:
        """Take a memory snapshot"""
        if not self.enabled:
            return None

        current, peak = tracemalloc.get_traced_memory()

        snap = MemorySnapshot(
            name=name,
            current_mb=current / 1024 / 1024,
            peak_mb=peak / 1024 / 1024
        )

        if not self.snapshots:
            self.start_memory = snap.current_mb

        self.snapshots.append(snap)
        return snap

    def print_current(self, name: str, console=None):
        """Take snapshot and print current memory"""
        snap = self.snapshot(name)
        if not snap:
            return

        delta = snap.current_mb - self.start_memory

        if console:
            console.print(
                f"[dim]💾 {name}: {snap.current_mb:.1f}MB "
                f"(Δ{delta:+.1f}MB, peak: {snap.peak_mb:.1f}MB)[/dim]"
            )
        else:
            print(f"💾 {name}: {snap.current_mb:.1f}MB (Δ{delta:+.1f}MB, peak: {snap.peak_mb:.1f}MB)")

    def report(self, console=None):
        """Print simple memory report"""
        if not self.enabled or not self.snapshots:
            return

        output = console.print if console else print

        output("\n" + "="*80)
        output("MEMORY PROFILE REPORT")
        output("="*80)

        for i, snap in enumerate(self.snapshots):
            if i == 0:
                output(f"{snap.name:40s} {snap.current_mb:8.1f}MB (baseline)")
            else:
                delta = snap.current_mb - self.snapshots[i-1].current_mb
                total_delta = snap.current_mb - self.start_memory
                output(
                    f"{snap.name:40s} {snap.current_mb:8.1f}MB "
                    f"(+{delta:6.1f}MB) [total: +{total_delta:6.1f}MB]"
                )

        output("="*80)
        if len(self.snapshots) > 1:
            total = self.snapshots[-1].current_mb - self.start_memory
            peak = max(s.peak_mb for s in self.snapshots)
            output(f"Total Growth: {total:+.1f}MB")
            output(f"Peak Memory:  {peak:.1f}MB")
        output("="*80 + "\n")

    def stop(self):
        """Stop profiling"""
        if self.enabled:
            tracemalloc.stop()
