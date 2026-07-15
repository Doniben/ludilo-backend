#!/usr/bin/env python3
"""
dataset.py — Dataset y DataLoader para training de LudiloNet.

Carga ventanas de audio + labels desde archivos .npz generados por generate_labels.py.
Soporta augmentation en tiempo real (pitch shift, time stretch, noise).

Formato de cada .npz:
    audio: [n_samples] (float32, 22050 Hz)
    contour: [n_frames, 264] (float32)
    note: [n_frames, 88] (float32)
    onset: [n_frames, 88] (float32)
    string_fret: [n_frames, 150] (float32)
    technique: [n_frames, 5] (float32)
"""
import os
import json
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader

# Constantes
AUDIO_SAMPLE_RATE = 22050
FFT_HOP = 256
AUDIO_WINDOW_LENGTH = 2  # seconds
AUDIO_N_SAMPLES = AUDIO_SAMPLE_RATE * AUDIO_WINDOW_LENGTH - FFT_HOP  # 43776


class LudiloDataset(Dataset):
    """
    Dataset de ventanas de audio + labels para training de LudiloNet.

    Args:
        manifest_path: Path al manifest.json con splits
        split: "train", "val", o "test"
        augment: Si True, aplica augmentation en tiempo real
        max_items: Limitar número de items (para debug)
    """

    def __init__(
        self,
        manifest_path: str,
        split: str = "train",
        augment: bool = False,
        max_items: int = 0,
    ):
        self.split = split
        self.augment = augment and split == "train"

        # Cargar manifest
        with open(manifest_path) as f:
            manifest = json.load(f)

        items = manifest["splits"][split]
        if max_items > 0:
            items = items[:max_items]

        # Recoger todos los archivos .npz
        self.files = []
        for item in items:
            for file_path in item["files"]:
                if os.path.exists(file_path):
                    self.files.append(file_path)

        print(f"LudiloDataset [{split}]: {len(self.files)} windows from {len(items)} items")

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        """
        Retorna un ejemplo de training.

        Returns:
            Dict con:
                audio: [AUDIO_N_SAMPLES] tensor
                contour: [n_frames, 264] tensor
                note: [n_frames, 88] tensor
                onset: [n_frames, 88] tensor
                string_fret: [n_frames, 150] tensor
                technique: [n_frames, 5] tensor
        """
        data = np.load(self.files[idx])

        audio = data["audio"].astype(np.float32)
        contour = data["contour"].astype(np.float32)
        note = data["note"].astype(np.float32)
        onset = data["onset"].astype(np.float32)
        string_fret = data["string_fret"].astype(np.float32)
        technique = data["technique"].astype(np.float32)

        # Asegurar longitud correcta de audio
        if len(audio) < AUDIO_N_SAMPLES:
            audio = np.pad(audio, (0, AUDIO_N_SAMPLES - len(audio)))
        elif len(audio) > AUDIO_N_SAMPLES:
            audio = audio[:AUDIO_N_SAMPLES]

        # Augmentation (solo audio, labels no cambian para augmentation simple)
        if self.augment:
            audio = self._augment_audio(audio)

        return {
            "audio": torch.from_numpy(audio),
            "contour": torch.from_numpy(contour),
            "note": torch.from_numpy(note),
            "onset": torch.from_numpy(onset),
            "string_fret": torch.from_numpy(string_fret),
            "technique": torch.from_numpy(technique),
        }

    def _augment_audio(self, audio: np.ndarray) -> np.ndarray:
        """
        Augmentation en tiempo real del audio.
        NO cambia pitch ni timing (eso cambiaría los labels).
        Solo transformaciones que no afectan las notas.
        """
        # 1. Variación de ganancia (±6 dB)
        if random.random() < 0.5:
            gain_db = random.uniform(-6, 6)
            gain = 10 ** (gain_db / 20)
            audio = audio * gain

        # 2. Ruido aditivo (SNR 20-40 dB)
        if random.random() < 0.3:
            snr_db = random.uniform(20, 40)
            signal_power = np.mean(audio ** 2)
            noise_power = signal_power / (10 ** (snr_db / 10))
            noise = np.random.randn(len(audio)).astype(np.float32) * np.sqrt(noise_power)
            audio = audio + noise

        # 3. Clipping suave (simula distorsión leve)
        if random.random() < 0.1:
            threshold = random.uniform(0.7, 0.95)
            audio = np.clip(audio, -threshold, threshold)

        # 4. Normalización final (evitar clipping)
        peak = np.max(np.abs(audio))
        if peak > 1.0:
            audio = audio / peak * 0.95

        return audio


class LudiloDatasetFromDir(Dataset):
    """
    Dataset que carga directamente de un directorio de .npz files.
    Más simple, para cuando no hay manifest.
    """

    def __init__(self, data_dir: str, augment: bool = False, max_files: int = 0):
        self.augment = augment
        self.files = sorted([
            str(f) for f in Path(data_dir).rglob("*.npz")
        ])
        if max_files > 0:
            self.files = self.files[:max_files]
        print(f"LudiloDatasetFromDir: {len(self.files)} files from {data_dir}")

    def __len__(self) -> int:
        return len(self.files)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        data = np.load(self.files[idx])
        audio = data["audio"].astype(np.float32)

        if len(audio) < AUDIO_N_SAMPLES:
            audio = np.pad(audio, (0, AUDIO_N_SAMPLES - len(audio)))
        elif len(audio) > AUDIO_N_SAMPLES:
            audio = audio[:AUDIO_N_SAMPLES]

        return {
            "audio": torch.from_numpy(audio),
            "contour": torch.from_numpy(data["contour"].astype(np.float32)),
            "note": torch.from_numpy(data["note"].astype(np.float32)),
            "onset": torch.from_numpy(data["onset"].astype(np.float32)),
            "string_fret": torch.from_numpy(data["string_fret"].astype(np.float32)),
            "technique": torch.from_numpy(data["technique"].astype(np.float32)),
        }


def create_dataloaders(
    manifest_path: str,
    batch_size: int = 8,
    num_workers: int = 4,
    augment_train: bool = True,
    max_items: int = 0,
) -> Tuple[DataLoader, DataLoader, DataLoader]:
    """
    Crea DataLoaders para train, val, test.

    Args:
        manifest_path: Path al manifest.json
        batch_size: Batch size (ajustar según VRAM)
        num_workers: Workers para carga de datos
        augment_train: Si True, augmentation en train
        max_items: Limitar items por split (debug)

    Returns:
        (train_loader, val_loader, test_loader)
    """
    train_ds = LudiloDataset(manifest_path, "train", augment=augment_train, max_items=max_items)
    val_ds = LudiloDataset(manifest_path, "val", augment=False, max_items=max_items)
    test_ds = LudiloDataset(manifest_path, "test", augment=False, max_items=max_items)

    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True,
        num_workers=num_workers, pin_memory=True, drop_last=True
    )
    val_loader = DataLoader(
        val_ds, batch_size=batch_size, shuffle=False,
        num_workers=num_workers, pin_memory=True
    )
    test_loader = DataLoader(
        test_ds, batch_size=batch_size, shuffle=False,
        num_workers=num_workers, pin_memory=True
    )

    return train_loader, val_loader, test_loader
