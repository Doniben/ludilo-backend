#!/usr/bin/env python3
"""
train.py — Training loop para LudiloNet.

Fine-tune de Basic Pitch para transcripción de guitarra con tablatura.
Optimizado para NVIDIA A1000 (6GB VRAM).

Uso:
    # Fase 1: Solo cabezas (encoder congelado)
    python train.py --phase 1 --dataset training/data/dataset/manifest.json

    # Fase 2: End-to-end (todo descongelado, lr bajo)
    python train.py --phase 2 --dataset training/data/dataset/manifest.json --resume checkpoints/phase1_best.pt

    # Fase 3: Con cabezas de tablatura
    python train.py --phase 3 --dataset training/data/dataset/manifest.json --resume checkpoints/phase2_best.pt

Requiere:
    pip install torch nnAudio tensorboard tqdm
"""
import os
import sys
import time
import argparse
import logging
from pathlib import Path
from typing import Dict

import torch
import torch.nn as nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import CosineAnnealingLR, ReduceLROnPlateau
from torch.cuda.amp import GradScaler, autocast

try:
    from torch.utils.tensorboard import SummaryWriter
except ImportError:
    SummaryWriter = None

from tqdm import tqdm

from model import LudiloNet, LudiloNetLoss
from dataset import create_dataloaders

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


# --- Configuración por fase ---

CONFIGS = {
    1: {
        "name": "Phase 1: Frozen encoder, train heads only",
        "freeze_encoder": True,
        "include_tab_heads": False,     # Solo contour/note/onset primero
        "lr": 1e-3,
        "batch_size": 8,                # Cabe en 6GB con encoder congelado
        "epochs": 30,
        "scheduler": "cosine",
        "weight_decay": 1e-4,
    },
    2: {
        "name": "Phase 2: End-to-end fine-tune",
        "freeze_encoder": False,
        "include_tab_heads": False,
        "lr": 1e-5,                     # LR muy bajo para no destruir features
        "batch_size": 4,                # Más bajo porque backprop por todo el modelo
        "epochs": 20,
        "scheduler": "plateau",
        "weight_decay": 1e-5,
    },
    3: {
        "name": "Phase 3: Add tablature heads",
        "freeze_encoder": True,         # Congelar encoder, solo tab heads
        "include_tab_heads": True,
        "lr": 5e-4,
        "batch_size": 6,
        "epochs": 25,
        "scheduler": "cosine",
        "weight_decay": 1e-4,
    },
    4: {
        "name": "Phase 4: Final end-to-end with everything",
        "freeze_encoder": False,
        "include_tab_heads": True,
        "lr": 5e-6,                     # LR mínimo
        "batch_size": 4,
        "epochs": 15,
        "scheduler": "plateau",
        "weight_decay": 1e-5,
    },
}


def train_epoch(model: nn.Module, loader, optimizer, criterion, scaler,
                device: str, epoch: int, use_amp: bool = True) -> Dict[str, float]:
    """Entrena una epoch completa."""
    model.train()
    running_losses = {}
    n_batches = 0

    pbar = tqdm(loader, desc=f"Epoch {epoch} [train]", leave=False)
    for batch in pbar:
        audio = batch["audio"].to(device)
        targets = {k: v.to(device) for k, v in batch.items() if k != "audio"}

        optimizer.zero_grad()

        if use_amp:
            with autocast():
                predictions = model(audio)
                losses = criterion(predictions, targets)
            scaler.scale(losses["total"]).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            predictions = model(audio)
            losses = criterion(predictions, targets)
            losses["total"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

        # Acumular losses
        for k, v in losses.items():
            running_losses[k] = running_losses.get(k, 0) + v.item()
        n_batches += 1

        pbar.set_postfix(loss=losses["total"].item())

    # Promediar
    avg_losses = {k: v / max(n_batches, 1) for k, v in running_losses.items()}
    return avg_losses


@torch.no_grad()
def validate(model: nn.Module, loader, criterion, device: str) -> Dict[str, float]:
    """Evalúa en validation set."""
    model.eval()
    running_losses = {}
    n_batches = 0

    for batch in tqdm(loader, desc="Validating", leave=False):
        audio = batch["audio"].to(device)
        targets = {k: v.to(device) for k, v in batch.items() if k != "audio"}

        predictions = model(audio)
        losses = criterion(predictions, targets)

        for k, v in losses.items():
            running_losses[k] = running_losses.get(k, 0) + v.item()
        n_batches += 1

    avg_losses = {k: v / max(n_batches, 1) for k, v in running_losses.items()}
    return avg_losses


def save_checkpoint(model, optimizer, scheduler, epoch, val_loss, path):
    """Guarda checkpoint."""
    torch.save({
        "epoch": epoch,
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        "scheduler_state_dict": scheduler.state_dict() if scheduler else None,
        "val_loss": val_loss,
    }, path)


def main():
    parser = argparse.ArgumentParser(description="Train LudiloNet")
    parser.add_argument("--phase", type=int, required=True, choices=[1, 2, 3, 4],
                       help="Fase de entrenamiento")
    parser.add_argument("--dataset", required=True, help="Path al manifest.json")
    parser.add_argument("--resume", default=None, help="Checkpoint para continuar")
    parser.add_argument("--bp-weights", default=None,
                       help="Pesos de Basic Pitch pre-entrenados (.pth)")
    parser.add_argument("--output-dir", default="training/checkpoints",
                       help="Directorio para checkpoints")
    parser.add_argument("--device", default="cuda", help="Device (cuda/cpu)")
    parser.add_argument("--epochs", type=int, default=0, help="Override epochs")
    parser.add_argument("--batch-size", type=int, default=0, help="Override batch size")
    parser.add_argument("--lr", type=float, default=0, help="Override learning rate")
    parser.add_argument("--no-amp", action="store_true", help="Desactivar mixed precision")
    parser.add_argument("--max-items", type=int, default=0, help="Limitar dataset (debug)")
    parser.add_argument("--grad-accum", type=int, default=1,
                       help="Gradient accumulation steps (simular batch más grande)")
    args = parser.parse_args()

    # Config
    config = CONFIGS[args.phase]
    epochs = args.epochs or config["epochs"]
    batch_size = args.batch_size or config["batch_size"]
    lr = args.lr or config["lr"]
    use_amp = not args.no_amp and args.device == "cuda"

    log.info(f"{'='*60}")
    log.info(f"LudiloNet Training — {config['name']}")
    log.info(f"{'='*60}")
    log.info(f"  Phase: {args.phase}")
    log.info(f"  Epochs: {epochs}")
    log.info(f"  Batch size: {batch_size}")
    log.info(f"  Learning rate: {lr}")
    log.info(f"  Device: {args.device}")
    log.info(f"  Mixed precision: {use_amp}")
    log.info(f"  Gradient accumulation: {args.grad_accum}")

    # Device
    device = args.device
    if device == "cuda" and not torch.cuda.is_available():
        log.warning("CUDA no disponible, usando CPU")
        device = "cpu"
        use_amp = False

    if device == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        log.info(f"  GPU: {gpu_name} ({gpu_mem:.1f} GB)")

    # Modelo
    model = LudiloNet(
        freeze_encoder=config["freeze_encoder"],
        include_tab_heads=config["include_tab_heads"],
    ).to(device)

    # Cargar pesos
    if args.bp_weights and args.phase == 1:
        log.info(f"Cargando pesos de Basic Pitch: {args.bp_weights}")
        model.load_basic_pitch_weights(args.bp_weights)
    elif args.resume:
        log.info(f"Resumiendo desde: {args.resume}")
        checkpoint = torch.load(args.resume, map_location=device)
        # Cargar state dict (parcial si cambiaron las cabezas)
        own_state = model.state_dict()
        loaded = 0
        for k, v in checkpoint["model_state_dict"].items():
            if k in own_state and own_state[k].shape == v.shape:
                own_state[k] = v
                loaded += 1
        model.load_state_dict(own_state)
        log.info(f"  Cargados {loaded} tensores del checkpoint")

    # Contar parámetros
    params = LudiloNet.count_parameters(model)
    log.info(f"  Params: {params['total']:,} total, {params['trainable']:,} trainable, "
             f"{params['frozen']:,} frozen")

    # Dataset
    train_loader, val_loader, _ = create_dataloaders(
        args.dataset,
        batch_size=batch_size,
        num_workers=2,  # Conservador para no saturar RAM
        augment_train=True,
        max_items=args.max_items,
    )
    log.info(f"  Train batches: {len(train_loader)}")
    log.info(f"  Val batches: {len(val_loader)}")

    # Loss
    criterion = LudiloNetLoss(include_tab_heads=config["include_tab_heads"]).to(device)

    # Optimizer
    optimizer = AdamW(
        filter(lambda p: p.requires_grad, model.parameters()),
        lr=lr,
        weight_decay=config["weight_decay"],
    )

    # Scheduler
    if config["scheduler"] == "cosine":
        scheduler = CosineAnnealingLR(optimizer, T_max=epochs, eta_min=lr * 0.01)
    else:
        scheduler = ReduceLROnPlateau(optimizer, mode="min", factor=0.5, patience=3)

    # Mixed precision scaler
    scaler = GradScaler() if use_amp else None

    # TensorBoard
    os.makedirs(args.output_dir, exist_ok=True)
    tb_dir = os.path.join(args.output_dir, f"runs/phase{args.phase}")
    writer = SummaryWriter(tb_dir) if SummaryWriter else None

    # Training loop
    best_val_loss = float("inf")
    patience_counter = 0
    patience_limit = 7  # Early stopping

    log.info(f"\nIniciando training...")

    for epoch in range(1, epochs + 1):
        t0 = time.time()

        # Train
        train_losses = train_epoch(model, train_loader, optimizer, criterion,
                                   scaler, device, epoch, use_amp)

        # Validate
        val_losses = validate(model, val_loader, criterion, device)

        # Scheduler step
        if config["scheduler"] == "cosine":
            scheduler.step()
        else:
            scheduler.step(val_losses["total"])

        elapsed = time.time() - t0
        current_lr = optimizer.param_groups[0]["lr"]

        # Log
        log.info(
            f"Epoch {epoch:3d}/{epochs} | "
            f"Train: {train_losses['total']:.4f} | "
            f"Val: {val_losses['total']:.4f} | "
            f"LR: {current_lr:.2e} | "
            f"Time: {elapsed:.0f}s"
        )

        # TensorBoard
        if writer:
            for k, v in train_losses.items():
                writer.add_scalar(f"train/{k}", v, epoch)
            for k, v in val_losses.items():
                writer.add_scalar(f"val/{k}", v, epoch)
            writer.add_scalar("lr", current_lr, epoch)

        # Checkpoint
        if val_losses["total"] < best_val_loss:
            best_val_loss = val_losses["total"]
            patience_counter = 0
            best_path = os.path.join(args.output_dir, f"phase{args.phase}_best.pt")
            save_checkpoint(model, optimizer, scheduler, epoch, best_val_loss, best_path)
            log.info(f"  ✓ Best model saved (val_loss={best_val_loss:.4f})")
        else:
            patience_counter += 1

        # Early stopping
        if patience_counter >= patience_limit:
            log.info(f"  Early stopping at epoch {epoch} (patience={patience_limit})")
            break

        # Checkpoint periódico
        if epoch % 5 == 0:
            periodic_path = os.path.join(args.output_dir, f"phase{args.phase}_epoch{epoch}.pt")
            save_checkpoint(model, optimizer, scheduler, epoch, val_losses["total"], periodic_path)

    # Final
    log.info(f"\nTraining completo!")
    log.info(f"  Mejor val_loss: {best_val_loss:.4f}")
    log.info(f"  Checkpoint: {args.output_dir}/phase{args.phase}_best.pt")

    if writer:
        writer.close()

    # VRAM usage final
    if device == "cuda":
        mem_used = torch.cuda.max_memory_allocated() / 1e9
        log.info(f"  Peak VRAM: {mem_used:.2f} GB")


if __name__ == "__main__":
    main()
