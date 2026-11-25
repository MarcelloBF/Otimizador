"""Teste de desempenho para comparar o PC antes e depois das otimizações.

Mede: CPU (1 núcleo e todos), largura de banda da memória, disco (sequencial e 4K aleatório,
sem cache do Windows) e latência do sistema (atraso para acordar uma thread).
"""
from __future__ import annotations

import ctypes
import datetime as dt
import json
import os
import random
import statistics
import threading
import time
import zlib
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable

from .utils import data_dir

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
winmm = ctypes.WinDLL("winmm")


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    unit: str
    higher_better: bool
    reference: float  # valor de um PC "médio" = 1000 pontos
    weight: float = 1.0


METRICS = [
    Metric("cpu_single", "CPU — 1 núcleo", "MB/s", True, 15, 1.0),
    Metric("cpu_multi", "CPU — todos os núcleos", "MB/s", True, 70, 1.0),
    Metric("mem_bw", "Memória RAM (cópia)", "GB/s", True, 8, 0.7),
    Metric("disk_seq_read", "Disco — leitura sequencial", "MB/s", True, 450, 0.6),
    Metric("disk_seq_write", "Disco — escrita sequencial", "MB/s", True, 350, 0.6),
    Metric("disk_4k", "Disco — leitura 4K aleatória", "IOPS", True, 6000, 0.8),
    Metric("latency", "Latência do sistema (média)", "ms", False, 0.6, 0.8),
    Metric("latency_p99", "Latência do sistema (pior 1%)", "ms", False, 1.5, 0.5),
]
METRICS_BY_KEY = {m.key: m for m in METRICS}

# --------------------------------------------------------------------------- CPU


def _payload() -> bytes:
    # Dados semi-compressíveis e determinísticos (texto + ruído), 4 MB
    rnd = random.Random(42)
    words = [bytes(rnd.choices(b"abcdefghijklmnopqrstuvwxyz", k=rnd.randint(2, 9))) for _ in range(5000)]
    out = bytearray()
    while len(out) < 4 * 1024 * 1024:
        out += rnd.choice(words) + b" "
        if rnd.random() < 0.05:
            out += rnd.randbytes(8)
    return bytes(out)


def _compress_for(data: bytes, seconds: float, stop: threading.Event | None = None) -> float:
    done, t0 = 0, time.perf_counter()
    while True:
        zlib.compress(data, 6)  # zlib libera o GIL -> paraleliza de verdade entre threads
        done += len(data)
        el = time.perf_counter() - t0
        if el >= seconds or (stop and stop.is_set()):
            return done / el / 1024**2


def bench_cpu_single(seconds=3.0) -> float:
    data = _payload()
    _compress_for(data, 0.3)  # aquecimento (sai do modo econômico)
    return _compress_for(data, seconds)


def bench_cpu_multi(seconds=3.0) -> float:
    data = _payload()
    n = os.cpu_count() or 4
    with ThreadPoolExecutor(n) as ex:
        list(ex.map(lambda _: _compress_for(data, 0.3), range(n)))
        rates = list(ex.map(lambda _: _compress_for(data, seconds), range(n)))
    return sum(rates)


# --------------------------------------------------------------------------- memória


def bench_memory(size_mb=256, rounds=6) -> float:
    src = bytearray(os.urandom(1024 * 1024)) * size_mb
    dst = bytearray(len(src))
    best = 0.0
    for _ in range(rounds):
        t0 = time.perf_counter()
        dst[:] = src  # memmove em C
        el = time.perf_counter() - t0
        best = max(best, len(src) / el / 1024**3)
    del src, dst
    return best


# --------------------------------------------------------------------------- disco (sem cache)

GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
OPEN_ALWAYS, OPEN_EXISTING = 4, 3
FILE_FLAG_NO_BUFFERING, FILE_FLAG_WRITE_THROUGH, FILE_FLAG_DELETE_ON_CLOSE = 0x20000000, 0x80000000, 0x04000000
FILE_FLAG_RANDOM_ACCESS, FILE_FLAG_SEQUENTIAL_SCAN = 0x10000000, 0x08000000
INVALID_HANDLE = ctypes.c_void_p(-1).value
MEM_COMMIT, MEM_RESERVE, MEM_RELEASE, PAGE_READWRITE = 0x1000, 0x2000, 0x8000, 0x04

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                 wintypes.DWORD, wintypes.HANDLE]
kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
kernel32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD]
kernel32.VirtualAlloc.restype = ctypes.c_void_p
kernel32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _open(path, access, disposition, flags):
    h = kernel32.CreateFileW(path, access, 0, None, disposition, flags, None)
    if h in (None, INVALID_HANDLE):
        raise OSError(ctypes.get_last_error(), f"Não foi possível abrir {path}")
    return h


def bench_disk(path: str | None = None, size_mb=512, chunk_mb=4, rand_seconds=3.0) -> dict:
    """Retorna {'disk_seq_write', 'disk_seq_read', 'disk_4k'} medidos no disco do sistema."""
    path = path or os.path.join(os.environ.get("TEMP", "C:\\Windows\\Temp"), "otimizador_bench.tmp")
    chunk = chunk_mb * 1024 * 1024
    buf = kernel32.VirtualAlloc(None, chunk, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)  # alinhado à página
    ctypes.memmove(buf, os.urandom(chunk), chunk)  # dados aleatórios: SSDs com compressão não "trapaceiam"
    n = wintypes.DWORD()
    total = size_mb * 1024 * 1024
    res = {}
    try:
        h = _open(path, GENERIC_WRITE, OPEN_ALWAYS, FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH)
        try:
            t0 = time.perf_counter()
            for _ in range(total // chunk):
                if not kernel32.WriteFile(h, buf, chunk, ctypes.byref(n), None):
                    raise OSError(ctypes.get_last_error(), "Falha na escrita")
            res["disk_seq_write"] = total / (time.perf_counter() - t0) / 1024**2
        finally:
            kernel32.CloseHandle(h)

        h = _open(path, GENERIC_READ, OPEN_EXISTING, FILE_FLAG_NO_BUFFERING | FILE_FLAG_SEQUENTIAL_SCAN)
        try:
            t0 = time.perf_counter()
            for _ in range(total // chunk):
                kernel32.ReadFile(h, buf, chunk, ctypes.byref(n), None)
            res["disk_seq_read"] = total / (time.perf_counter() - t0) / 1024**2

            blocks = total // 4096
            rnd = random.Random(7)
            ops, t0 = 0, time.perf_counter()
            while True:
                kernel32.SetFilePointerEx(h, rnd.randrange(blocks) * 4096, None, 0)
                kernel32.ReadFile(h, buf, 4096, ctypes.byref(n), None)
                ops += 1
                if ops % 64 == 0 and time.perf_counter() - t0 >= rand_seconds:
                    break
            res["disk_4k"] = ops / (time.perf_counter() - t0)
        finally:
            kernel32.CloseHandle(h)
    finally:
        kernel32.VirtualFree(buf, 0, MEM_RELEASE)
        try:
            os.remove(path)
        except OSError:
            pass
    return res


# --------------------------------------------------------------------------- latência


def bench_latency(samples=1500) -> dict:
    """Pede para dormir 1 ms e mede quanto passou do previsto (atraso de agendamento)."""
    winmm.timeBeginPeriod(1)
    try:
        over = []
        for _ in range(samples):
            t0 = time.perf_counter()
            time.sleep(0.001)
            over.append(max(0.0, (time.perf_counter() - t0) * 1000 - 1.0))
    finally:
        winmm.timeEndPeriod(1)
    over.sort()
    return {"latency": statistics.mean(over), "latency_p99": over[int(len(over) * 0.99) - 1]}


# --------------------------------------------------------------------------- execução completa

STEPS = [
    ("CPU — 1 núcleo", lambda: {"cpu_single": bench_cpu_single()}),
    ("CPU — todos os núcleos", lambda: {"cpu_multi": bench_cpu_multi()}),
    ("Memória RAM", lambda: {"mem_bw": bench_memory()}),
    ("Disco do sistema", bench_disk),
    ("Latência do sistema", bench_latency),
]


def score(results: dict) -> int:
    """Pontuação geral: média geométrica ponderada em relação a um PC de referência (= 1000)."""
    import math

    tot_w, acc = 0.0, 0.0
    for m in METRICS:
        v = results.get(m.key)
        if not v or v <= 0:
            continue
        ratio = v / m.reference if m.higher_better else m.reference / v
        acc += m.weight * math.log(max(ratio, 1e-3))
        tot_w += m.weight
    return round(1000 * math.exp(acc / tot_w)) if tot_w else 0


def run_all(progress: Callable[[int, int, str], None] | None = None) -> dict:
    results = {}
    for i, (name, fn) in enumerate(STEPS):
        if progress:
            progress(i, len(STEPS), name)
        try:
            results.update(fn())
        except Exception as e:  # noqa: BLE001
            results.setdefault("_errors", []).append(f"{name}: {e}")
    if progress:
        progress(len(STEPS), len(STEPS), "Concluído")
    return results


# --------------------------------------------------------------------------- histórico


def _hist_path():
    return data_dir() / "benchmarks.json"


def load_history() -> list[dict]:
    try:
        return json.loads(_hist_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []


def save_run(label: str, results: dict, context: dict | None = None) -> dict:
    hist = load_history()
    run = {"id": int(time.time() * 1000), "label": label, "date": dt.datetime.now().isoformat(timespec="seconds"),
           "results": {k: v for k, v in results.items() if not k.startswith("_")}, "errors": results.get("_errors", []),
           "score": score(results), "context": context or {}}
    hist.append(run)
    _hist_path().write_text(json.dumps(hist, indent=1, ensure_ascii=False), encoding="utf-8")
    return run


def delete_run(run_id: int):
    hist = [r for r in load_history() if r["id"] != run_id]
    _hist_path().write_text(json.dumps(hist, indent=1, ensure_ascii=False), encoding="utf-8")


def compare(base: dict, new: dict) -> dict[str, float]:
    """Diferença percentual por métrica (positivo = melhorou)."""
    out = {}
    for m in METRICS:
        a, b = base["results"].get(m.key), new["results"].get(m.key)
        if not a or not b:
            continue
        out[m.key] = ((b - a) / a * 100) if m.higher_better else ((a - b) / a * 100)
    return out


NOISE_PCT = 5.0  # diferenças menores que isso são variação normal entre execuções


if __name__ == "__main__":
    r = run_all(lambda i, n, s: print(f"[{i}/{n}] {s}", flush=True))
    for k, v in r.items():
        print(k, v)
    print("score", score(r))
