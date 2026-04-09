#!/usr/bin/env python3
"""
Grafica en tiempo real Intensidad (u.a.) vs Angulo (grados)
recibidos desde un ChipKIT Uno32 por puerto serial.

Protocolo esperado (una linea por muestra):
1) "angulo,intensidad"  -> ejemplo: 45.0,823
2) "A=45.0 I=823"       -> tambien soportado

Uso:
python grafica_tiempo_real_chipkit.py --port COM5 --baudrate 115200
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import serial
from serial import SerialException


CSV_PATTERN = re.compile(
    r"^\s*([+-]?\d+(?:\.\d+)?)\s*[,;\t ]\s*([+-]?\d+(?:\.\d+)?)\s*$"
)
TAG_PATTERN = re.compile(
    r"A\s*=\s*([+-]?\d+(?:\.\d+)?)\s*[,;\t ]*I\s*=\s*([+-]?\d+(?:\.\d+)?)",
    flags=re.IGNORECASE,
)


@dataclass
class Config:
    port: str
    baudrate: int
    timeout: float
    max_points: int
    refresh_ms: int
    min_angle: float
    max_angle: float
    min_intensity: float
    max_intensity: float


def parse_line(line: str) -> Optional[tuple[float, float]]:
    """Devuelve (angulo, intensidad) o None si no se puede parsear."""
    line = line.strip()
    if not line:
        return None

    csv_match = CSV_PATTERN.match(line)
    if csv_match:
        return float(csv_match.group(1)), float(csv_match.group(2))

    tag_match = TAG_PATTERN.search(line)
    if tag_match:
        return float(tag_match.group(1)), float(tag_match.group(2))

    return None


def auto_scale(current_min: float, current_max: float, values: deque[float]) -> tuple[float, float]:
    """Ajuste simple de ejes en funcion de los datos visibles."""
    if not values:
        return current_min, current_max

    vmin = min(values)
    vmax = max(values)
    if vmin == vmax:
        margin = max(1.0, abs(vmin) * 0.05)
        return vmin - margin, vmax + margin

    span = vmax - vmin
    margin = span * 0.08
    return vmin - margin, vmax + margin


def run(cfg: Config) -> None:
    try:
        ser = serial.Serial(cfg.port, cfg.baudrate, timeout=cfg.timeout)
    except SerialException as exc:
        print(f"No se pudo abrir el puerto {cfg.port}: {exc}")
        sys.exit(1)

    angles: deque[float] = deque(maxlen=cfg.max_points)
    intensities: deque[float] = deque(maxlen=cfg.max_points)

    fig, ax = plt.subplots(figsize=(10, 5.5))
    (line_plot,) = ax.plot([], [], lw=2.0, color="#0B6E4F")

    ax.set_title("Intensidad (u.a.) vs Angulo (grados) - Tiempo real")
    ax.set_xlabel("Angulo (grados)")
    ax.set_ylabel("Intensidad (u.a.)")
    ax.grid(alpha=0.3)
    ax.set_xlim(cfg.min_angle, cfg.max_angle)
    ax.set_ylim(cfg.min_intensity, cfg.max_intensity)

    status_text = ax.text(
        0.02,
        0.97,
        "Esperando datos...",
        transform=ax.transAxes,
        va="top",
        fontsize=10,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.7, edgecolor="#CCCCCC"),
    )

    last_update_time = time.time()
    sample_count = 0

    def update(_frame: int):
        nonlocal last_update_time, sample_count

        while ser.in_waiting > 0:
            raw = ser.readline().decode("utf-8", errors="replace")
            parsed = parse_line(raw)
            if parsed is None:
                continue

            angle, intensity = parsed
            angles.append(angle)
            intensities.append(intensity)
            sample_count += 1

        if angles:
            line_plot.set_data(angles, intensities)
            xmin, xmax = auto_scale(cfg.min_angle, cfg.max_angle, angles)
            ymin, ymax = auto_scale(cfg.min_intensity, cfg.max_intensity, intensities)
            ax.set_xlim(xmin, xmax)
            ax.set_ylim(ymin, ymax)

        now = time.time()
        elapsed = now - last_update_time
        if elapsed > 0:
            rate = sample_count / elapsed
            status_text.set_text(
                f"Muestras: {len(angles)} | Tasa: {rate:.1f} Hz | Ultimo punto: "
                f"{angles[-1]:.2f} deg, {intensities[-1]:.2f} u.a."
                if angles
                else "Esperando datos..."
            )
        else:
            status_text.set_text("Esperando datos...")

        if elapsed >= 1.0:
            sample_count = 0
            last_update_time = now

        return line_plot, status_text

    def on_close(_event):
        if ser.is_open:
            ser.close()

    fig.canvas.mpl_connect("close_event", on_close)
    # Keep a strong reference to the animation to avoid garbage collection.
    fig._anim = FuncAnimation(fig, update, interval=cfg.refresh_ms, blit=False, cache_frame_data=False)

    try:
        plt.tight_layout()
        plt.show()
    finally:
        if ser.is_open:
            ser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grafica en tiempo real Intensidad (u.a.) vs Angulo (grados) desde ChipKIT Uno32"
    )
    parser.add_argument("--port", required=True, help="Puerto serial, por ejemplo COM5")
    parser.add_argument("--baudrate", type=int, default=115200, help="Velocidad serial")
    parser.add_argument("--timeout", type=float, default=0.05, help="Timeout serial (s)")
    parser.add_argument("--max-points", type=int, default=1500, help="Maximo de puntos visibles")
    parser.add_argument("--refresh-ms", type=int, default=40, help="Refresco de grafica en ms")
    parser.add_argument("--min-angle", type=float, default=0.0, help="Minimo angulo inicial")
    parser.add_argument("--max-angle", type=float, default=180.0, help="Maximo angulo inicial")
    parser.add_argument(
        "--min-intensity", type=float, default=0.0, help="Minima intensidad inicial"
    )
    parser.add_argument(
        "--max-intensity", type=float, default=1023.0, help="Maxima intensidad inicial"
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    cfg = Config(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        max_points=args.max_points,
        refresh_ms=args.refresh_ms,
        min_angle=args.min_angle,
        max_angle=args.max_angle,
        min_intensity=args.min_intensity,
        max_intensity=args.max_intensity,
    )

    run(cfg)


if __name__ == "__main__":
    main()
