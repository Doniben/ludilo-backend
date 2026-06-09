"""
Ludilo — Sprint A: Alineación temporal GP ↔ Audio con DTW
Alinea las notas del Guitar Pro al audio real usando Dynamic Time Warping
sobre chroma features.
"""
import numpy as np
import librosa
import pretty_midi
import guitarpro
import mir_eval
import json
from pathlib import Path

EVAL_DIR = Path("/tmp/ludilo-eval")
TICKS_PER_QUARTER = 960
SR = 22050
HOP = 512


def gp_to_midi_for_chroma(gp_path):
    """Convert GP to a PrettyMIDI object for chroma extraction.
    Uses header.start ticks directly — proven to match audio duration.
    """
    song = guitarpro.parse(str(gp_path))
    tempo = song.tempo
    # In 6/8 at 73 BPM: quarter note = 60/73 = 0.822s
    # tick 960 = 1 quarter note = 0.822s
    sec_per_tick = (60.0 / tempo) / TICKS_PER_QUARTER

    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)

    for track in song.tracks:
        if track.isPercussionTrack:
            continue
        if "easy" in track.name.lower():
            continue

        instrument = pretty_midi.Instrument(program=25, name=track.name)

        for measure in track.measures:
            measure_start_tick = measure.header.start

            # Check for tempo changes in this measure
            for voice in measure.voices:
                current_tick = measure_start_tick
                for beat in voice.beats:
                    dur_value = beat.duration.value
                    beat_ticks = int(TICKS_PER_QUARTER * 4 / dur_value)
                    if beat.duration.isDotted:
                        beat_ticks = int(beat_ticks * 1.5)
                    if beat.duration.tuplet and beat.duration.tuplet.enters > 0:
                        beat_ticks = int(beat_ticks * beat.duration.tuplet.times / beat.duration.tuplet.enters)

                    if beat.effect and hasattr(beat.effect, 'mixTableChange') and beat.effect.mixTableChange:
                        mtc = beat.effect.mixTableChange
                        if mtc.tempo:
                            tempo = mtc.tempo.value
                            sec_per_tick = (60.0 / tempo) / TICKS_PER_QUARTER

                    for note in beat.notes:
                        if note.type in (guitarpro.NoteType.rest, guitarpro.NoteType.tie):
                            continue

                        pitch = note.realValue if hasattr(note, 'realValue') else note.value
                        onset_sec = current_tick * sec_per_tick
                        offset_sec = (current_tick + beat_ticks) * sec_per_tick

                        instrument.notes.append(pretty_midi.Note(
                            velocity=80, pitch=pitch,
                            start=onset_sec, end=offset_sec
                        ))

                    current_tick += beat_ticks

        if instrument.notes:
            pm.instruments.append(instrument)

    return pm


def align_with_dtw(audio_path, gp_pm):
    """Align GP chroma to audio chroma using DTW. Returns time warping function."""
    # Audio chroma (use chroma_stft — no numba dependency)
    y, sr = librosa.load(str(audio_path), sr=SR)
    chroma_audio = librosa.feature.chroma_stft(y=y, sr=sr, hop_length=HOP)

    # GP chroma from piano_roll
    fs = SR / HOP  # frames per second
    piano_roll = gp_pm.get_piano_roll(fs=fs)
    chroma_gp = np.zeros((12, piano_roll.shape[1]))
    for pitch in range(128):
        chroma_gp[pitch % 12] += piano_roll[pitch]
    # Normalize
    col_max = chroma_gp.max(axis=0, keepdims=True) + 1e-8
    chroma_gp = chroma_gp / col_max

    # DTW (subsequence — GP may be shorter/longer than audio)
    D, wp = librosa.sequence.dtw(chroma_audio, chroma_gp, subseq=True)

    return wp, chroma_audio.shape[1], chroma_gp.shape[1]


def warp_gp_notes(gp_pm, wp, n_frames_audio, n_frames_gp):
    """Apply DTW warping to GP note onsets/offsets."""
    from scipy.interpolate import interp1d

    # wp is (N, 2) where wp[i] = (audio_frame, gp_frame) — reversed from docs
    # Sort by gp_frame for interpolation
    wp_sorted = wp[wp[:, 1].argsort()]

    # Remove duplicate gp_frame entries (keep first)
    _, unique_idx = np.unique(wp_sorted[:, 1], return_index=True)
    wp_unique = wp_sorted[unique_idx]

    gp_times = librosa.frames_to_time(wp_unique[:, 1], sr=SR, hop_length=HOP)
    audio_times = librosa.frames_to_time(wp_unique[:, 0], sr=SR, hop_length=HOP)

    audio_duration = librosa.frames_to_time(n_frames_audio, sr=SR, hop_length=HOP)

    warp_fn = interp1d(gp_times, audio_times, bounds_error=False,
                        fill_value=(audio_times[0], audio_times[-1]))

    warped_notes = []
    for instrument in gp_pm.instruments:
        for note in instrument.notes:
            new_onset = float(warp_fn(note.start))
            new_offset = float(warp_fn(note.end))

            # Clip to valid range
            if np.isnan(new_onset) or np.isinf(new_onset) or new_onset < 0:
                new_onset = 0.0
            if np.isnan(new_offset) or np.isinf(new_offset):
                new_offset = new_onset + 0.1
            if new_offset <= new_onset:
                new_offset = new_onset + 0.05
            if new_onset > audio_duration:
                continue  # Skip notes beyond audio

            warped_notes.append((new_onset, new_offset, note.pitch))

    return warped_notes


def evaluate_aligned(warped_ref, est_notes, label=""):
    """Evaluate with aligned reference."""
    if not warped_ref or not est_notes:
        return {"f1": 0, "precision": 0, "recall": 0}

    ref_intervals = np.array([[n[0], n[1]] for n in warped_ref])
    ref_pitches = np.array([n[2] for n in warped_ref], dtype=float)
    est_intervals = np.array([[n[0], n[1]] for n in est_notes])
    est_pitches = np.array([n[2] for n in est_notes], dtype=float)

    ref_hz = mir_eval.util.midi_to_hz(ref_pitches)
    est_hz = mir_eval.util.midi_to_hz(est_pitches)

    p, r, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
        ref_intervals, ref_hz, est_intervals, est_hz,
        onset_tolerance=0.1, pitch_tolerance=50.0, offset_ratio=None
    )
    return {"precision": round(p * 100, 2), "recall": round(r * 100, 2), "f1": round(f1 * 100, 2)}


def main():
    print("=" * 60)
    print("SPRINT A: Alineación temporal con DTW")
    print("=" * 60)

    # Step 1: Convert GP to MIDI
    print("\n1. Convirtiendo GP a MIDI sintético...")
    gp_pm = gp_to_midi_for_chroma(EVAL_DIR / "gp/nothing_else_matters.gp3")
    total_notes = sum(len(i.notes) for i in gp_pm.instruments)
    print(f"   {total_notes} notas, {len(gp_pm.instruments)} instrumentos")
    print(f"   Duración GP: {gp_pm.get_end_time():.1f}s")

    # Step 2: Load audio
    print("\n2. Cargando audio del stem de guitarra...")
    audio_path = EVAL_DIR / "audio_guitar.mp3"
    y, sr = librosa.load(str(audio_path), sr=SR)
    print(f"   Duración audio: {len(y)/sr:.1f}s")

    # Step 3: DTW alignment
    print("\n3. Calculando DTW (puede tardar ~30s)...")
    wp, n_audio, n_gp = align_with_dtw(audio_path, gp_pm)
    print(f"   Warping path: {len(wp)} puntos")
    print(f"   Frames audio: {n_audio}, Frames GP: {n_gp}")

    # Step 4: Warp GP notes
    print("\n4. Aplicando warping a notas GP...")
    warped_notes = warp_gp_notes(gp_pm, wp, n_audio, n_gp)
    print(f"   {len(warped_notes)} notas alineadas")
    print(f"   Rango temporal: {min(n[0] for n in warped_notes):.1f}s - {max(n[1] for n in warped_notes):.1f}s")

    # Step 5: Re-evaluate
    print("\n5. Re-evaluando con referencia alineada...")

    # Load generated MIDIs
    from evaluate import midi_to_note_events
    mt3_guitar = midi_to_note_events(EVAL_DIR / "mt3/guitar.mid")
    bp_guitar = midi_to_note_events(EVAL_DIR / "bp/guitar.mid")

    # Filter warped_notes to guitar range (40-88)
    warped_guitar = [(o, off, p) for o, off, p in warped_notes if 40 <= p <= 88]

    mt3_result = evaluate_aligned(warped_guitar, mt3_guitar, "MT3+")
    bp_result = evaluate_aligned(warped_guitar, bp_guitar, "BP")

    print(f"\n{'─' * 50}")
    print(f"  ANTES (sin alinear):")
    print(f"    MT3+ F1 = 8.9%  |  BP F1 = 10.0%")
    print(f"\n  DESPUÉS (con DTW):")
    print(f"    MT3+ F1 = {mt3_result['f1']}%  (P={mt3_result['precision']}%, R={mt3_result['recall']}%)")
    print(f"    BP   F1 = {bp_result['f1']}%  (P={bp_result['precision']}%, R={bp_result['recall']}%)")
    print(f"{'─' * 50}")

    improvement_mt3 = mt3_result['f1'] - 8.9
    improvement_bp = bp_result['f1'] - 10.0
    print(f"\n  Mejora MT3+: {'+' if improvement_mt3 > 0 else ''}{improvement_mt3:.1f} puntos")
    print(f"  Mejora BP:   {'+' if improvement_bp > 0 else ''}{improvement_bp:.1f} puntos")

    # Save
    results = {
        "before_alignment": {"mt3_f1": 8.9, "bp_f1": 10.0},
        "after_alignment": {"mt3": mt3_result, "bp": bp_result},
        "warped_notes_count": len(warped_guitar),
        "audio_duration": len(y) / sr,
        "gp_duration": gp_pm.get_end_time()
    }
    with open(EVAL_DIR / "dtw_results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✅ Resultados: {EVAL_DIR / 'dtw_results.json'}")


if __name__ == "__main__":
    main()
