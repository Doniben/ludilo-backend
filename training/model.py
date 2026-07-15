#!/usr/bin/env python3
"""
model.py — LudiloNet: Fine-tune de Basic Pitch para guitarra con tablatura.

Extiende el modelo BasicPitchTorch con cabezas adicionales para:
- String/Fret (posición en diapasón)
- Technique (slide, hammer, pull, bend, normal)

Arquitectura:
    Input: Audio raw → CQT → Harmonic Stacking → CNN encoder
    Output: contour (264), note (88), onset (88), string_fret (150), technique (5)
"""
import math
from typing import List, Dict

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

try:
    from nnAudio.features import CQT2010v2
except ImportError:
    print("ERROR: pip install nnAudio")
    raise

# --- Constantes (matching Basic Pitch) ---

AUDIO_SAMPLE_RATE = 22050
FFT_HOP = 256
ANNOTATIONS_BASE_FREQUENCY = 27.5
ANNOTATIONS_N_SEMITONES = 88
CONTOURS_BINS_PER_SEMITONE = 3
MAX_N_SEMITONES = int(np.floor(12.0 * np.log2(0.5 * AUDIO_SAMPLE_RATE / ANNOTATIONS_BASE_FREQUENCY)))

# LudiloNet extras
N_STRINGS = 6
N_FRETS = 25
N_STRING_FRET_BINS = N_STRINGS * N_FRETS  # 150
N_TECHNIQUE_CLASSES = 6  # normal, slide, hammer, pull, bend, strum

# Chord vocabulary
# 12 roots × 12 quality types + "N" (no chord) = 145 clases
# Reducido a las más comunes para empezar
CHORD_QUALITIES = ["maj", "min", "7", "maj7", "min7", "dim", "aug", "sus4", "sus2", "min7b5", "6", "min6"]
N_CHORD_ROOTS = 12
N_CHORD_CLASSES = N_CHORD_ROOTS * len(CHORD_QUALITIES) + 1  # +1 for "N" (no chord) = 145


def log_base_b(x, base):
    return torch.log(x) / torch.log(torch.tensor([base], dtype=x.dtype, device=x.device))


def normalized_log(inputs):
    """Rescale to dB, normalized 0-1."""
    power = torch.square(inputs)
    log_power = 10 * log_base_b(power + 1e-10, 10)
    log_power_min = torch.amin(log_power, dim=(1, 2)).reshape(inputs.shape[0], 1, 1)
    log_power_offset = log_power - log_power_min
    log_power_offset_max = torch.amax(log_power_offset, dim=(1, 2)).reshape(inputs.shape[0], 1, 1)
    log_power_normalized = log_power_offset / log_power_offset_max
    log_power_normalized = torch.nan_to_num(log_power_normalized, nan=0.0)
    return log_power_normalized.reshape(inputs.shape)


class HarmonicStacking(nn.Module):
    """Stack harmonics of CQT for multi-harmonic input."""

    def __init__(self, bins_per_semitone: int, harmonics: List[float], n_output_freqs: int):
        super().__init__()
        self.bins_per_semitone = bins_per_semitone
        self.harmonics = harmonics
        self.n_output_freqs = n_output_freqs
        self.shifts = [int(round(12.0 * bins_per_semitone * math.log2(h))) for h in harmonics]

    @torch.no_grad()
    def forward(self, x):
        hcqt = []
        for shift in self.shifts:
            if shift == 0:
                cur_cqt = x
            elif shift > 0:
                cur_cqt = F.pad(x[:, :, shift:], (0, shift))
            else:
                cur_cqt = F.pad(x[:, :, :shift], (-shift, 0))
            hcqt.append(cur_cqt)
        hcqt = torch.stack(hcqt, dim=1)
        hcqt = hcqt[:, :, :, :self.n_output_freqs]
        return hcqt


class LudiloNet(nn.Module):
    """
    LudiloNet: Fine-tuned Basic Pitch con cabezas de tablatura.

    Fases de entrenamiento:
        1. Cargar pesos pre-entrenados de Basic Pitch en el encoder
        2. Fine-tune con datos de guitarra
        3. Agregar cabezas de string_fret y technique

    Args:
        stack_harmonics: Lista de armónicos para harmonic stacking
        freeze_encoder: Si True, congela el encoder (solo entrena cabezas)
        include_tab_heads: Si True, incluye cabezas de tablatura (string_fret + technique)
    """

    def __init__(
        self,
        stack_harmonics: List[float] = [0.5, 1, 2, 3, 4, 5, 6, 7],
        freeze_encoder: bool = False,
        include_tab_heads: bool = True,
    ):
        super().__init__()
        self.stack_harmonics = stack_harmonics
        self.include_tab_heads = include_tab_heads

        n_output_freqs = ANNOTATIONS_N_SEMITONES * CONTOURS_BINS_PER_SEMITONE

        if len(stack_harmonics) > 0:
            self.hs = HarmonicStacking(
                bins_per_semitone=CONTOURS_BINS_PER_SEMITONE,
                harmonics=stack_harmonics,
                n_output_freqs=n_output_freqs,
            )
            num_in_channels = len(stack_harmonics)
        else:
            num_in_channels = 1

        # --- Encoder (from Basic Pitch) ---
        self.bn_layer = nn.BatchNorm2d(1, eps=0.001)

        # Contour head (shared encoder part)
        self.conv_contour = nn.Sequential(
            nn.Conv2d(num_in_channels, 8, kernel_size=(3, 3 * 13), padding="same"),
            nn.BatchNorm2d(8, eps=0.001),
            nn.ReLU(),
            nn.Conv2d(8, 1, kernel_size=5, padding="same"),
            nn.Sigmoid(),
        )

        # Note head
        self.conv_note = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=7, stride=(1, 3)),
            nn.ReLU(),
            nn.Conv2d(32, 1, kernel_size=(7, 3), padding="same"),
            nn.Sigmoid(),
        )

        # Onset head
        self.conv_onset_pre = nn.Sequential(
            nn.Conv2d(num_in_channels, 32, kernel_size=5, stride=(1, 3)),
            nn.BatchNorm2d(32, eps=0.001),
            nn.ReLU(),
        )
        self.conv_onset_post = nn.Sequential(
            nn.Conv2d(32 + 1, 1, kernel_size=3, stride=1, padding="same"),
            nn.Sigmoid(),
        )

        # --- Cabezas de tablatura (NUEVAS) ---
        if include_tab_heads:
            # String/Fret head: toma note output (88) y predice posición (150)
            # Input: note output [batch, 1, frames, 88]
            self.string_fret_head = nn.Sequential(
                nn.Conv2d(1, 16, kernel_size=(5, 5), padding="same"),
                nn.BatchNorm2d(16, eps=0.001),
                nn.ReLU(),
                nn.Conv2d(16, 8, kernel_size=(3, 3), padding="same"),
                nn.ReLU(),
                # Reshape 88 → 150 con linear layer por frame
            )
            # Linear para mapear de 88 bins a 150 bins (string×fret)
            self.string_fret_linear = nn.Linear(88 * 8, N_STRING_FRET_BINS)

            # Technique head: clasifica técnica por frame (6 clases)
            # Input: concatenación de note + onset features
            self.technique_head = nn.Sequential(
                nn.Linear(88 + 88, 64),
                nn.ReLU(),
                nn.Dropout(0.2),
                nn.Linear(64, N_TECHNIQUE_CLASSES),
            )

            # Chord head: detecta acorde activo por frame
            # Input: note activations (88 bins = pitch class info)
            # Usa ventana temporal más amplia (contexto de ~0.5s) para capturar acordes
            self.chord_head = nn.Sequential(
                nn.Conv1d(88, 64, kernel_size=21, padding=10),  # ~250ms context
                nn.BatchNorm1d(64),
                nn.ReLU(),
                nn.Conv1d(64, 32, kernel_size=11, padding=5),   # ~125ms context
                nn.ReLU(),
                nn.Conv1d(32, N_CHORD_CLASSES, kernel_size=1),  # per-frame classification
            )

        # CQT layer (creada dinámicamente en forward)
        self._cqt_layer = None

        # Freeze encoder si se pide
        if freeze_encoder:
            self._freeze_encoder()

    def _freeze_encoder(self):
        """Congela las capas del encoder (para entrenar solo cabezas)."""
        for param in self.bn_layer.parameters():
            param.requires_grad = False
        for param in self.conv_contour.parameters():
            param.requires_grad = False
        for param in self.conv_note.parameters():
            param.requires_grad = False
        for param in self.conv_onset_pre.parameters():
            param.requires_grad = False
        for param in self.conv_onset_post.parameters():
            param.requires_grad = False

    def unfreeze_encoder(self):
        """Descongela el encoder para fine-tune end-to-end."""
        for param in self.parameters():
            param.requires_grad = True

    def _get_cqt(self, x):
        """Compute CQT from audio input."""
        n_harmonics = len(self.stack_harmonics)
        n_semitones = min(
            int(np.ceil(12.0 * np.log2(n_harmonics)) + ANNOTATIONS_N_SEMITONES),
            MAX_N_SEMITONES,
        )

        if self._cqt_layer is None or self._cqt_layer.n_bins != n_semitones * CONTOURS_BINS_PER_SEMITONE:
            self._cqt_layer = CQT2010v2(
                sr=AUDIO_SAMPLE_RATE,
                hop_length=FFT_HOP,
                fmin=ANNOTATIONS_BASE_FREQUENCY,
                n_bins=n_semitones * CONTOURS_BINS_PER_SEMITONE,
                bins_per_octave=12 * CONTOURS_BINS_PER_SEMITONE,
                verbose=False,
            )
            self._cqt_layer.to(x.device)

        cqt = self._cqt_layer(x)
        cqt = torch.transpose(cqt, 1, 2)
        cqt = normalized_log(cqt)

        cqt = cqt.unsqueeze(1)
        cqt = self.bn_layer(cqt)
        cqt = cqt.squeeze(1)

        return cqt

    def forward(self, x: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Forward pass.

        Args:
            x: Audio tensor [batch, n_samples]

        Returns:
            Dict con:
                contour: [batch, n_frames, 264]
                note: [batch, n_frames, 88]
                onset: [batch, n_frames, 88]
                string_fret: [batch, n_frames, 150] (si include_tab_heads)
                technique: [batch, n_frames, 5] (si include_tab_heads)
        """
        # CQT
        cqt = self._get_cqt(x)

        # Harmonic stacking
        if hasattr(self, "hs"):
            cqt = self.hs(cqt)
        else:
            cqt = cqt.unsqueeze(1)

        # --- Contour ---
        x_contour = self.conv_contour(cqt)

        # --- Note ---
        x_contour_for_note = F.pad(x_contour, (2, 2, 3, 3))
        x_note = self.conv_note(x_contour_for_note)

        # --- Onset ---
        cqt_for_onset = F.pad(cqt, (1, 1, 2, 2))
        x_onset_pre = self.conv_onset_pre(cqt_for_onset)
        x_onset_pre = torch.cat([x_note, x_onset_pre], dim=1)
        x_onset = self.conv_onset_post(x_onset_pre)

        outputs = {
            "contour": x_contour.squeeze(1),    # [batch, frames, 264]
            "note": x_note.squeeze(1),          # [batch, frames, 88]
            "onset": x_onset.squeeze(1),        # [batch, frames, 88]
        }

        # --- Cabezas de tablatura ---
        if self.include_tab_heads:
            batch, frames, _ = outputs["note"].shape

            # String/Fret: usar features de note
            note_4d = x_note  # [batch, 1, frames, 88]
            sf_features = self.string_fret_head(note_4d)  # [batch, 8, frames, 88]
            sf_features = sf_features.permute(0, 2, 1, 3)  # [batch, frames, 8, 88]
            sf_features = sf_features.reshape(batch, frames, -1)  # [batch, frames, 8*88]
            string_fret_out = self.string_fret_linear(sf_features)  # [batch, frames, 150]
            string_fret_out = torch.sigmoid(string_fret_out)
            outputs["string_fret"] = string_fret_out

            # Technique: usar note + onset como input
            note_flat = outputs["note"]     # [batch, frames, 88]
            onset_flat = outputs["onset"]   # [batch, frames, 88]
            tech_input = torch.cat([note_flat, onset_flat], dim=-1)  # [batch, frames, 176]
            technique_out = self.technique_head(tech_input)  # [batch, frames, 6]
            outputs["technique"] = technique_out

            # Chord: usar note activations con contexto temporal
            note_for_chord = outputs["note"].permute(0, 2, 1)  # [batch, 88, frames]
            chord_out = self.chord_head(note_for_chord)  # [batch, N_CHORD_CLASSES, frames]
            chord_out = chord_out.permute(0, 2, 1)  # [batch, frames, N_CHORD_CLASSES]
            outputs["chord"] = chord_out

        return outputs

    def load_basic_pitch_weights(self, weights_path: str):
        """
        Carga pesos pre-entrenados de Basic Pitch (solo las capas compatibles).
        Las cabezas nuevas (string_fret, technique) se quedan con pesos aleatorios.
        """
        state_dict = torch.load(weights_path, map_location="cpu")

        # Filtrar solo las keys que existen en nuestro modelo
        own_state = self.state_dict()
        loaded = 0
        skipped = 0

        for name, param in state_dict.items():
            if name in own_state and own_state[name].shape == param.shape:
                own_state[name].copy_(param)
                loaded += 1
            else:
                skipped += 1

        print(f"Loaded {loaded} params from Basic Pitch, skipped {skipped}")
        self.load_state_dict(own_state)

    @staticmethod
    def count_parameters(model) -> Dict[str, int]:
        """Cuenta parámetros entrenables vs totales."""
        total = sum(p.numel() for p in model.parameters())
        trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
        return {"total": total, "trainable": trainable, "frozen": total - trainable}


# --- Loss Functions ---

class LudiloNetLoss(nn.Module):
    """
    Loss combinada para LudiloNet.

    L = L_contour + L_note + L_onset + λ₁·L_string_fret + λ₂·L_technique + λ₃·L_chord
    """

    def __init__(self, lambda_string_fret: float = 0.3, lambda_technique: float = 0.1,
                 lambda_chord: float = 0.2, include_tab_heads: bool = True):
        super().__init__()
        self.lambda_sf = lambda_string_fret
        self.lambda_tech = lambda_technique
        self.lambda_chord = lambda_chord
        self.include_tab_heads = include_tab_heads

        # BCE para las cabezas de pitch (como BP original)
        self.bce = nn.BCELoss()
        # BCE para string_fret (multi-label)
        self.bce_sf = nn.BCELoss()
        # Cross-entropy para technique (multi-clase por frame)
        self.ce_tech = nn.CrossEntropyLoss()
        # Cross-entropy para chord (multi-clase por frame)
        self.ce_chord = nn.CrossEntropyLoss(ignore_index=-1)

    def forward(self, predictions: Dict[str, torch.Tensor],
                targets: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        """
        Calcula loss total y por componente.

        Args:
            predictions: Output del modelo
            targets: Labels ground truth

        Returns:
            Dict con loss total y por componente
        """
        losses = {}

        # Core losses (Binary Cross-Entropy)
        losses["contour"] = self.bce(predictions["contour"], targets["contour"])
        losses["note"] = self.bce(predictions["note"], targets["note"])
        losses["onset"] = self.bce(predictions["onset"], targets["onset"])

        total = losses["contour"] + losses["note"] + losses["onset"]

        # Tab losses
        if self.include_tab_heads and "string_fret" in predictions:
            losses["string_fret"] = self.bce_sf(
                predictions["string_fret"], targets["string_fret"]
            )
            total = total + self.lambda_sf * losses["string_fret"]

        if self.include_tab_heads and "technique" in predictions:
            # Technique: reshape para CrossEntropy [batch*frames, n_classes]
            tech_pred = predictions["technique"]
            tech_target = targets["technique"]

            batch, frames, n_cls = tech_pred.shape
            # Target: argmax para convertir one-hot a índice de clase
            tech_target_idx = tech_target.reshape(-1, n_cls).argmax(dim=-1)
            tech_pred_flat = tech_pred.reshape(-1, n_cls)

            losses["technique"] = self.ce_tech(tech_pred_flat, tech_target_idx)
            total = total + self.lambda_tech * losses["technique"]

        if self.include_tab_heads and "chord" in predictions:
            # Chord: CrossEntropy por frame
            chord_pred = predictions["chord"]  # [batch, frames, n_chord_classes]
            chord_target = targets["chord"]    # [batch, frames, n_chord_classes] (one-hot)

            batch, frames, n_cls = chord_pred.shape
            chord_target_idx = chord_target.reshape(-1, n_cls).argmax(dim=-1)
            chord_pred_flat = chord_pred.reshape(-1, n_cls)

            losses["chord"] = self.ce_chord(chord_pred_flat, chord_target_idx)
            total = total + self.lambda_chord * losses["chord"]

        losses["total"] = total
        return losses
